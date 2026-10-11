from conftest import png_bytes


def add(client, seed):
    r = client.post("/api/ingest", params={"commit": "true"}, files={"file": ("x.png", png_bytes(seed=seed))})
    return r.json()["item"]


def test_sync_returns_changes_since_a_rev_with_tombstones(client):
    a, b = add(client, 1), add(client, 2)
    first = client.get("/api/sync").json()
    assert [i["id"] for i in first["items"]] == [a["id"], b["id"]]
    assert first["has_more"] is False
    cursor = first["rev"]

    assert client.get("/api/sync", params={"since": cursor}).json()["items"] == []

    client.patch(f"/api/items/{a['id']}", json={"favorite": True})
    client.delete(f"/api/items/{b['id']}")
    coll = client.post("/api/collections", json={"name": "Frogs"}).json()
    again = client.get("/api/sync", params={"since": cursor}).json()
    assert again["items"][0]["id"] == a["id"] and again["items"][0]["favorite"] is True
    assert again["items"][1] == {"id": b["id"], "deleted": True, "rev": again["items"][1]["rev"]}
    assert [c["name"] for c in again["collections"]] == ["Frogs"]
    assert again["rev"] > cursor and coll["id"] == again["collections"][0]["id"]


def test_sync_pages_without_losing_rows(client):
    ids = [add(client, s)["id"] for s in range(1, 6)]
    seen, since = [], 0
    for _ in range(10):
        page = client.get("/api/sync", params={"since": since, "limit": 2}).json()
        seen += [i["id"] for i in page["items"]]
        since = page["rev"]
        if not page["has_more"]:
            break
    assert seen == ids


def test_server_info(client):
    add(client, 1)
    info = client.get("/api/server").json()
    assert info["items"] == 1 and info["unsorted"] == 1 and info["bytes"] > 0
    assert info["embeddings"]["state"] == "disabled"
