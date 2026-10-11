from conftest import png_bytes, tinted_png


def add(client, data, name="x.png", **form):
    r = client.post("/api/ingest", params={"commit": "true"}, files={"file": (name, data)}, data=form)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def test_semantic_search_ranks_by_look(client, embedder):
    red = add(client, tinted_png(0, 1), title="a")
    green = add(client, tinted_png(1, 2), title="b")
    blue = add(client, tinted_png(2, 3), title="c")

    r = client.get("/api/search", params={"q": "green"}).json()
    assert r["semantic"] is True
    assert [i["id"] for i in r["items"]][0] == green["id"]
    assert [i["id"] for i in client.get("/api/search", params={"q": "blue"}).json()["items"]][0] == blue["id"]
    assert [i["id"] for i in client.get("/api/search", params={"q": "red"}).json()["items"]][0] == red["id"]


def test_filters_compose_with_ranking(client, embedder):
    red = add(client, tinted_png(0, 1))
    red2 = add(client, tinted_png(0, 5))
    client.patch(f"/api/items/{red2['id']}", json={"favorite": True})
    r = client.get("/api/search", params={"q": "red", "favorite": "true"}).json()
    assert [i["id"] for i in r["items"]] == [red2["id"]]
    assert red["id"] not in [i["id"] for i in r["items"]]


def test_keyword_search_works_without_an_embedder(client):
    a = add(client, png_bytes(seed=1), title="smug frog")
    add(client, png_bytes(seed=2), title="sad cat")
    r = client.get("/api/search", params={"q": "frog"}).json()
    assert r["semantic"] is False
    assert [i["id"] for i in r["items"]] == [a["id"]]
    # tags are searchable too, and prefixes match
    client.patch(f"/api/items/{a['id']}", json={"tags": ["judging"]})
    assert [i["id"] for i in client.get("/api/search", params={"q": "judg"}).json()["items"]] == [a["id"]]


def test_similar_excludes_self_and_orders_by_distance(client, embedder):
    r1 = add(client, tinted_png(0, 1))
    r2 = add(client, tinted_png(0, 2))
    b = add(client, tinted_png(2, 3))
    sim = client.get(f"/api/items/{r1['id']}/similar").json()["items"]
    assert [i["id"] for i in sim] == [r2["id"], b["id"]]


def test_stage_suggests_near_duplicate_by_embedding_and_auto_tags(client, embedder):
    first = add(client, tinted_png(0, 1))
    client.patch(f"/api/items/{first['id']}", json={"tags": ["red"]})

    staged = client.post("/api/ingest", files={"file": ("n.png", tinted_png(0, 9))}).json()
    assert [n["item"]["id"] for n in staged["near"]] == [first["id"]]
    assert staged["near"][0]["similarity"] >= 0.94
    assert staged["auto_tags"] and staged["auto_tags"][0]["name"] == "red"
    assert "embedding" not in staged["meta"]

    # Committing with tags=None accepts the suggestions, recorded as auto tags with a score.
    item = client.post(f"/api/ingest/{staged['staged_id']}/commit", json={}).json()["item"]
    tag = next(t for t in item["tags"] if t["name"] == "red")
    assert tag["origin"] == "auto" and tag["score"] is not None

    # Removing a suggestion in the Save sheet means it is simply not in `tags`.
    staged2 = client.post("/api/ingest", files={"file": ("m.png", tinted_png(0, 11))}).json()
    item2 = client.post(f"/api/ingest/{staged2['staged_id']}/commit", json={"tags": []}).json()["item"]
    assert item2["tags"] == []


def test_embedding_status(client, embedder):
    add(client, tinted_png(0, 1))
    st = client.get("/api/embeddings/status").json()
    assert st["model"] == "fake-rgb" and st["items_without_vector"] == 0
