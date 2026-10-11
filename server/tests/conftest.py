import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vault.config import get_settings


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    def factory(auth_disabled: bool = True) -> TestClient:
        monkeypatch.setenv("VAULT_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("VAULT_AUTH_DISABLED", "true" if auth_disabled else "false")
        monkeypatch.setenv("VAULT_EMBED_MODEL", "none")  # never download real weights in tests
        monkeypatch.setenv("VAULT_WORKER_ENABLED", "false")  # tests run jobs explicitly
        get_settings.cache_clear()
        from vault.main import create_app

        c = TestClient(create_app())
        c.__enter__()
        return c

    made = []

    def tracked(**kw):
        c = factory(**kw)
        made.append(c)
        return c

    yield tracked
    for c in made:
        c.__exit__(None, None, None)
    get_settings.cache_clear()
    from vault.ml.registry import set_embedder

    set_embedder(None)


class ColourEmbedder:
    """Deterministic stand-in for CLIP: an image's embedding is its mean colour, text names a colour."""

    key = "fake-rgb"
    dim = 3
    WORDS = {"red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1)}

    def embed_images(self, images):
        import numpy as np

        out = []
        for im in images:
            v = np.asarray(im.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(axis=0) + 1e-3
            out.append(v / np.linalg.norm(v))
        return np.stack(out).astype(np.float32)

    def embed_texts(self, texts):
        import numpy as np

        out = []
        for t in texts:
            word = t.removeprefix("a reaction image of ").strip().split(" ")[-1]
            if word in self.WORDS:
                v = np.array(self.WORDS[word], dtype=np.float32) + 0.01
            else:  # unrelated words land in the grey diagonal, far from any pure colour
                v = np.ones(3, dtype=np.float32) * (1 + (hash(word) % 7) / 100)
            out.append(v / np.linalg.norm(v))
        return np.stack(out).astype(np.float32)


@pytest.fixture
def embedder():
    from vault.ml.registry import set_embedder

    e = ColourEmbedder()
    set_embedder(e)
    return e


def tinted_png(channel: int, seed: int, size=(48, 48)) -> bytes:
    """Noise image whose colour comes mostly from one channel (0=r, 1=g, 2=b)."""
    img = _noise(size, seed)
    px = [tuple(v if i == channel else v // 16 for i, v in enumerate(p)) for p in img.getdata()]
    out = Image.new("RGB", size)
    out.putdata(px)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def client(make_client):
    return make_client()


def _noise(size, seed):
    import random

    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size[0] * size[1])])
    return img


def png_bytes(size=(64, 48), seed=1, mode="RGB") -> bytes:
    img = _noise(size, seed).convert(mode)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def gif_bytes(frames=4, size=(32, 32)) -> bytes:
    imgs = [Image.new("RGB", size, (i * 60, 255 - i * 60, 90)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, "GIF", save_all=True, append_images=imgs[1:], duration=100, loop=0)
    return buf.getvalue()


def webp_anim_bytes(frames=5, size=(40, 40)) -> bytes:
    imgs = [Image.new("RGBA", size, (i * 50, 100, 200, 255)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, "WEBP", save_all=True, append_images=imgs[1:], duration=80, loop=0)
    return buf.getvalue()
