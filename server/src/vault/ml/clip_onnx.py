import logging
import os
import threading
from pathlib import Path

import httpx
import numpy as np
import onnxruntime as ort
from PIL import Image
from tokenizers import Tokenizer

log = logging.getLogger("vault.ml")

REPO = "Xenova/clip-vit-base-patch32"
BASE = f"https://huggingface.co/{REPO}/resolve/main"
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
SIZE = 224
CONTEXT = 77
EOT = 49407


def _files(precision: str) -> list[str]:
    suffix = "_quantized" if precision == "int8" else ""
    return ["tokenizer.json", f"onnx/vision_model{suffix}.onnx", f"onnx/text_model{suffix}.onnx"]


def _fetch(name: str, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    log.info("downloading %s", name)
    with httpx.stream("GET", f"{BASE}/{name}", follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    os.replace(part, dest)


def _l2(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float32)
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12)


class ClipOnnx:
    """OpenAI CLIP ViT-B/32 as separate vision and text ONNX graphs (Xenova export)."""

    key = "clip-b32"
    dim = 512

    def __init__(self, model_dir: Path, precision: str = "fp32"):
        for name in _files(precision):
            _fetch(name, model_dir / name)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
        providers = ["CPUExecutionProvider"]
        suffix = "_quantized" if precision == "int8" else ""
        self._vision = ort.InferenceSession(str(model_dir / f"onnx/vision_model{suffix}.onnx"), opts, providers=providers)
        self._text = ort.InferenceSession(str(model_dir / f"onnx/text_model{suffix}.onnx"), opts, providers=providers)
        self._tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tok.enable_truncation(CONTEXT)
        self._tok.enable_padding(length=CONTEXT, pad_id=EOT, pad_token="<|endoftext|>")
        self._lock = threading.Lock()  # one inference at a time keeps memory and latency predictable
        self._v_out = self._pick(self._vision, "image_embeds")
        self._t_out = self._pick(self._text, "text_embeds")

    @staticmethod
    def _pick(session: ort.InferenceSession, preferred: str) -> str:
        names = [o.name for o in session.get_outputs()]
        if preferred in names:
            return preferred
        raise RuntimeError(f"model has no '{preferred}' output (found {names})")

    @staticmethod
    def _preprocess(img: Image.Image) -> np.ndarray:
        img = img.convert("RGB")
        w, h = img.size
        scale = SIZE / min(w, h)
        img = img.resize((max(SIZE, round(w * scale)), max(SIZE, round(h * scale))), Image.Resampling.BICUBIC)
        w, h = img.size
        left, top = (w - SIZE) // 2, (h - SIZE) // 2
        img = img.crop((left, top, left + SIZE, top + SIZE))
        arr = (np.asarray(img, dtype=np.float32) / 255.0 - MEAN) / STD
        return arr.transpose(2, 0, 1)

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        batch = np.stack([self._preprocess(i) for i in images]).astype(np.float32)
        name = self._vision.get_inputs()[0].name
        with self._lock:
            (out,) = self._vision.run([self._v_out], {name: batch})
        return _l2(out)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        enc = self._tok.encode_batch(texts)
        feeds = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64)}
        wanted = {i.name for i in self._text.get_inputs()}
        if "attention_mask" in wanted:
            feeds["attention_mask"] = np.array([e.attention_mask for e in enc], dtype=np.int64)
        with self._lock:
            (out,) = self._text.run([self._t_out], {k: v for k, v in feeds.items() if k in wanted})
        return _l2(out)
