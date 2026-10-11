import io

from PIL import Image

from conftest import gif_bytes, png_bytes, webp_anim_bytes


def upload(client, data: bytes, name="smug frog.png", **params):
    return client.post("/api/ingest", params=params, files={"file": (name, data)})


def test_stage_then_commit(client):
    r = upload(client, png_bytes())
    assert r.status_code == 200
    body = r.json()
    assert body["duplicate"] is None
    assert body["meta"]["kind"] == "image"
    assert body["meta"]["suggested_title"] == "smug frog"
    assert client.get(body["file_url"]).status_code == 200

    c = client.post(f"/api/ingest/{body['staged_id']}/commit",
                    json={"title": "Smug frog", "tags": ["Frog", " smug "]})
    assert c.status_code == 200
    item = c.json()["item"]
    assert item["title"] == "Smug frog"
    assert [t["name"] for t in item["tags"]] == ["frog", "smug"]
    assert item["urls"]["thumb"] == f"/media/{item['id']}/thumb"

    thumb = client.get(item["urls"]["thumb"])
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/webp"
    assert client.get(item["urls"]["original"]).content == png_bytes()
    assert client.get("/api/health").json()["items"] == 1


def test_exact_duplicate_is_reported_not_stored(client):
    first = upload(client, png_bytes(), commit="true").json()
    again = upload(client, png_bytes()).json()
    assert again["duplicate"] == "exact"
    assert again["item"]["id"] == first["item"]["id"]
    assert client.get("/api/health").json()["items"] == 1


def test_near_duplicate_is_flagged_with_similarity(client):
    big = png_bytes(size=(128, 96), seed=7)
    first = upload(client, big, commit="true").json()["item"]
    img = Image.open(io.BytesIO(big)).resize((64, 48))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    staged = upload(client, buf.getvalue(), name="small.png").json()
    assert staged["duplicate"] is None
    assert [n["item"]["id"] for n in staged["near"]] == [first["id"]]
    assert staged["near"][0]["similarity"] >= 0.9


def test_animated_gif_and_webp_get_preview_and_duration(client):
    gif = upload(client, gif_bytes(frames=4), name="a.gif", commit="true").json()["item"]
    assert gif["kind"] == "animated" and gif["frame_count"] == 4 and gif["duration_ms"] == 400
    assert "preview" in gif["urls"]
    assert client.get(gif["urls"]["preview"]).status_code == 200

    webp = upload(client, webp_anim_bytes(), name="b.webp", commit="true").json()["item"]
    assert webp["kind"] == "animated" and webp["mime"] == "image/webp"
    assert webp["has_alpha"] is False  # alpha channel present but fully opaque

    imgs = [Image.new("RGBA", (16, 16), (0, 0, 0, 0)) for _ in range(2)]
    buf = io.BytesIO()
    imgs[0].save(buf, "WEBP", save_all=True, append_images=imgs[1:], duration=50)
    clear = upload(client, buf.getvalue(), name="c.webp", commit="true").json()["item"]
    assert clear["has_alpha"] is True


def test_rejects_non_media(client):
    r = upload(client, b"just some text, not an image", name="note.png")
    assert r.status_code in (415, 422)


def test_rejects_empty_and_oversize(client, monkeypatch):
    assert upload(client, b"").status_code == 400
    from vault.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_bytes", 10)
    assert upload(client, png_bytes()).status_code == 413


def test_url_ingest_refuses_private_addresses(client):
    for url in ("http://127.0.0.1/x.png", "http://localhost:8420/api/health", "file:///etc/passwd"):
        r = client.post("/api/ingest", data={"url": url})
        assert r.status_code == 400, url


def test_requires_exactly_one_source(client):
    assert client.post("/api/ingest").status_code == 400


def test_deleted_item_can_be_saved_again(client):
    item = upload(client, png_bytes(), commit="true").json()["item"]
    assert client.delete(f"/api/items/{item['id']}").status_code == 204
    assert client.get(f"/api/items/{item['id']}").status_code == 404
    again = upload(client, png_bytes(), commit="true").json()
    assert again["duplicate"] is None
    assert again["item"]["id"] == item["id"]
