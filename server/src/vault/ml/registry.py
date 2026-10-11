"""Embedding model registry. One active embedder per process, loaded in the background."""
import logging
import threading
from typing import Protocol

import numpy as np
from PIL import Image

from vault.config import Settings

log = logging.getLogger("vault.ml")


class Embedder(Protocol):
    key: str
    dim: int

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        """(n, dim) float32, L2-normalised."""

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """(n, dim) float32, L2-normalised."""


_lock = threading.Lock()
_embedder: Embedder | None = None
_status = {"state": "idle", "error": None}  # idle | loading | ready | failed | disabled


def table_name(key: str) -> str:
    return "vec_" + "".join(c if c.isalnum() else "_" for c in key)


def get_embedder() -> Embedder | None:
    return _embedder


def status() -> dict:
    return dict(_status) | {"model": _embedder.key if _embedder else None}


def set_embedder(embedder: Embedder | None) -> None:
    """Install an embedder directly (tests, or a custom model)."""
    global _embedder
    with _lock:
        _embedder = embedder
        _status.update(state="ready" if embedder else "idle", error=None)


def _build(settings: Settings) -> Embedder:
    key = settings.embed_model
    if key == "clip-b32":
        from vault.ml.clip_onnx import ClipOnnx

        return ClipOnnx(settings.models_dir / key, precision=settings.embed_precision)
    raise ValueError(f"unknown embedding model '{key}'")


def _load(settings: Settings) -> None:
    global _embedder
    try:
        emb = _build(settings)
        with _lock:
            _embedder = emb
            _status.update(state="ready", error=None)
        log.info("embedding model %s ready (dim %d)", emb.key, emb.dim)
    except Exception as e:  # download or ONNX errors must not take the server down
        log.exception("could not load embedding model")
        _status.update(state="failed", error=str(e))


def warm(settings: Settings) -> None:
    """Start loading the configured model in a background thread. Safe to call repeatedly."""
    if settings.embed_model in ("", "none"):
        _status.update(state="disabled", error=None)
        return
    with _lock:
        if _embedder is not None or _status["state"] == "loading":
            return
        _status.update(state="loading", error=None)
    threading.Thread(target=_load, args=(settings,), name="embed-load", daemon=True).start()
