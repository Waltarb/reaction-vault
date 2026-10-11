import io

from PIL import Image

from conftest import gif_bytes, png_bytes


def clear_png(seed: int) -> bytes:
    img = Image.open(io.BytesIO(png_bytes(seed=seed))).convert("RGBA")
    img.putpixel((0, 0), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def add(client, data, **form):
    r = client.post("/api/ingest", params={"commit": "true"}, files={"file": ("x.png", data)}, data=form)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def test_list_filters_and_pagination(client):
    a = add(client, png_bytes(seed=1))
    b = add(client, gif_bytes())
    c = add(client, clear_png(3))

    ids = [i["id"] for i in client.get("/api/items").json()["items"]]
    assert ids == [c["id"], b["id"], a["id"]]

    assert [i["id"] for i in client.get("/api/items", params={"kind": "animated"}).json()["items"]] == [b["id"]]
    assert [i["id"] for i in client.get("/api/items", params={"kind": "static"}).json()["items"]] == [c["id"], a["id"]]
    assert [i["id"] for i in client.get("/api/items", params={"transparent": "true"}).json()["items"]] == [c["id"]]

    page = client.get("/api/items", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["next_cursor"] == b["id"]
    rest = client.get("/api/items", params={"limit": 2, "cursor": page["next_cursor"]}).json()
    assert [i["id"] for i in rest["items"]] == [a["id"]] and rest["next_cursor"] is None


def test_patch_favorite_tags_collections(client):
    item = add(client, png_bytes())
    coll = client.post("/api/collections", json={"name": "Frogs"}).json()
    assert client.post("/api/collections", json={"name": "frogs"}).status_code == 409

    p = client.patch(f"/api/items/{item['id']}",
                     json={"favorite": True, "tags": ["Smug", "frog"], "collection_ids": [coll["id"]],
                           "title": "Smug"}).json()
    assert p["favorite"] and p["title"] == "Smug" and p["collection_ids"] == [coll["id"]]

    assert [i["id"] for i in client.get("/api/items", params={"favorite": "true"}).json()["items"]] == [item["id"]]
    assert client.get("/api/items", params={"unsorted": "true"}).json()["items"] == []
    assert [i["id"] for i in client.get("/api/items", params={"tag": "SMUG"}).json()["items"]] == [item["id"]]
    assert client.get("/api/collections").json()[0]["count"] == 1
    assert client.get("/api/tags").json() == [{"name": "frog", "count": 1}, {"name": "smug", "count": 1}]

    client.delete(f"/api/collections/{coll['id']}")
    assert client.get(f"/api/items/{item['id']}").json()["collection_ids"] == []
    assert len(client.get("/api/items", params={"unsorted": "true"}).json()["items"]) == 1
    # The name can be reused after deletion.
    assert client.post("/api/collections", json={"name": "Frogs"}).status_code == 201


def test_revs_increase_on_every_change(client):
    item = add(client, png_bytes())
    r1 = client.get("/api/health").json()["rev"]
    client.patch(f"/api/items/{item['id']}", json={"favorite": True})
    r2 = client.get("/api/health").json()["rev"]
    assert r2 > r1
    assert client.get(f"/api/items/{item['id']}").json()["rev"] == r2


def test_auth_enforced_with_device_token(make_client):
    c = make_client(auth_disabled=False)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/items").status_code == 401

    from vault.api.deps import hash_token
    from vault.config import get_settings
    from vault.db.connection import connect

    db = connect(get_settings().db_path)
    db.execute("INSERT INTO devices (name, token_hash) VALUES ('t', ?)", (hash_token("secret"),))
    db.close()

    assert c.get("/api/items", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/api/items", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post("/api/session", json={"token": "secret"}).status_code == 204
    assert c.get("/api/items").status_code == 200  # cookie now set
