import shutil

import pytest

from vault.plugins import registry
from vault.plugins.base import Candidate, SearchPage
from vault.plugins.seventv.plugin import SevenTV, parse_emote

from conftest import png_bytes, tinted_png

EMOTE = {
    "id": "01FAPFR2T80009222ZMH048914",
    "name": "Chillin",
    "animated": True,
    "owner": {"username": "unice2nice"},
    "host": {
        "url": "//cdn.7tv.app/emote/01FAPFR2T80009222ZMH048914",
        "files": [
            {"name": "1x.webp", "format": "WEBP", "width": 32, "height": 32, "frame_count": 31, "size": 100},
            {"name": "2x.webp", "format": "WEBP", "width": 64, "height": 64, "frame_count": 31, "size": 200},
            {"name": "4x.webp", "format": "WEBP", "width": 128, "height": 128, "frame_count": 31, "size": 400},
            {"name": "4x.avif", "format": "AVIF", "width": 128, "height": 128, "frame_count": 31, "size": 300},
            {"name": "4x.gif", "format": "GIF", "width": 128, "height": 128, "frame_count": 31, "size": 900},
        ],
    },
}


def test_parse_emote_picks_webp_and_a_64px_preview():
    c = parse_emote(EMOTE)
    assert c.file_url == "https://cdn.7tv.app/emote/01FAPFR2T80009222ZMH048914/4x.webp"
    assert c.preview_url.endswith("/2x.webp")
    assert c.mime == "image/webp" and c.animated and c.width == 128
    assert c.page_url == "https://7tv.app/emotes/01FAPFR2T80009222ZMH048914"
    assert "file_url" not in c.public()


def test_parse_emote_skips_entries_without_files():
    assert parse_emote({"id": "X", "name": "n", "host": {"url": "//cdn", "files": []}}) is None


def test_seventv_search_builds_query_and_pages(monkeypatch):
    calls = []
    plugin = SevenTV(client=object())

    def fake_gql(query, variables):
        calls.append(variables)
        return {"emotes": {"count": 50, "items": [EMOTE]}}

    monkeypatch.setattr(plugin, "_gql", fake_gql)
    page = plugin.search("frog", animated=True, page=1, limit=24)
    assert calls[0]["f"]["animated"] is True and calls[0]["q"] == "frog"
    assert len(page.items) == 1 and page.has_more is True and page.total == 50


def test_seventv_resolve_rejects_malformed_ids():
    assert SevenTV(client=object()).resolve("../../etc/passwd") is None


class FakeSource:
    key = "fake"
    label = "Fake"

    def __init__(self):
        self.items = {
            "AAA": Candidate("fake", "AAA", "smug frog", "https://example.com/a-prev.png",
                             "https://example.com/a.png", "image/png", 48, 48, False, "https://example.com/a"),
            "BBB": Candidate("fake", "BBB", "sad cat", "https://example.com/b-prev.png",
                             "https://example.com/b.png", "image/png", 48, 48, False, "https://example.com/b"),
        }

    def search(self, query, *, animated, page, limit):
        return SearchPage(items=list(self.items.values()), page=page, has_more=False, total=2)

    def resolve(self, source_id):
        return self.items.get(source_id)


@pytest.fixture
def fake_source(monkeypatch, tmp_path):
    src = FakeSource()
    registry.register(src)
    payloads = {
        "https://example.com/a.png": tinted_png(0, 1), "https://example.com/a-prev.png": tinted_png(0, 1),
        "https://example.com/b.png": tinted_png(2, 2), "https://example.com/b-prev.png": tinted_png(2, 2),
    }

    def fake_download(url, staging_dir, max_bytes):
        import hashlib
        import uuid

        data = payloads[url]
        dest = staging_dir / f"{uuid.uuid4().hex}.part"
        dest.write_bytes(data)
        return dest, hashlib.sha256(data).hexdigest(), url.rsplit("/", 1)[-1], url

    monkeypatch.setattr("vault.api.discover.fetch.download", fake_download)
    yield src
    registry.reset()


def test_lists_sources(client, fake_source):
    keys = [s["key"] for s in client.get("/api/discover/sources").json()]
    assert "7tv" in keys and "fake" in keys


def test_search_marks_saved_and_hides_file_urls(client, fake_source):
    r = client.get("/api/discover/search", params={"q": "frog", "sources": "fake"}).json()
    assert [i["source_id"] for i in r["items"]] == ["AAA", "BBB"]
    assert all("file_url" not in i and i["saved_item_id"] is None for i in r["items"])

    saved = client.post("/api/discover/save", json={"source": "fake", "source_id": "AAA"}).json()
    assert saved["duplicate"] is None
    item = saved["item"]
    assert item["title"] == "smug frog" and item["source"] == "fake"
    assert {"name": "smug frog", "origin": "source", "score": None} in item["tags"]

    again = client.get("/api/discover/search", params={"q": "frog", "sources": "fake"}).json()
    assert again["items"][0]["saved_item_id"] == item["id"]
    assert again["items"][1]["saved_item_id"] is None


def test_save_twice_returns_existing(client, fake_source):
    first = client.post("/api/discover/save", json={"source": "fake", "source_id": "AAA"}).json()["item"]
    second = client.post("/api/discover/save", json={"source": "fake", "source_id": "AAA"}).json()
    assert second["duplicate"] == "source" and second["item"]["id"] == first["id"]
    assert client.get("/api/health").json()["items"] == 1


def test_save_unknown_source_or_id(client, fake_source):
    assert client.post("/api/discover/save", json={"source": "nope", "source_id": "x"}).status_code == 400
    assert client.post("/api/discover/save", json={"source": "fake", "source_id": "ZZZ"}).status_code == 404


def test_search_unknown_source_is_400(client, fake_source):
    assert client.get("/api/discover/search", params={"q": "a", "sources": "nope"}).status_code == 400


def test_failing_source_is_reported_not_fatal(client, fake_source, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(fake_source, "search", boom)
    r = client.get("/api/discover/search", params={"q": "a", "sources": "fake"}).json()
    assert r["items"] == [] and r["errors"] == {"fake": "unavailable"}


def test_rerank_by_picked_items(client, fake_source, embedder):
    # Picking a blue item should put the blue candidate first even though the source lists red first.
    blue = client.post("/api/ingest", params={"commit": "true"},
                       files={"file": ("b.png", tinted_png(2, 7))}).json()["item"]
    r = client.get("/api/discover/search",
                   params={"q": "x", "sources": "fake", "similar_to": str(blue["id"])}).json()
    assert r["reranked"] is True
    assert [i["source_id"] for i in r["items"]] == ["BBB", "AAA"]
    assert r["items"][0]["similarity"] > r["items"][1]["similarity"]
