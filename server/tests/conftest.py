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
