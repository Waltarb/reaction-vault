from datetime import UTC, datetime, timedelta

from vault.config import get_settings
from vault.db.connection import connect
from vault.main import create_app
from vault.maintenance import gc, import_folder

from conftest import gif_bytes, png_bytes


def _db():
    s = get_settings()
    return connect(s.db_path), s


def test_import_folder_adds_dedupes_and_skips(client, tmp_path):
    src = tmp_path / "pics"
    (src / "sub").mkdir(parents=True)
    (src / "a.png").write_bytes(png_bytes(seed=1))
    (src / "sub" / "b.gif").write_bytes(gif_bytes())
    (src / "sub" / "dup.png").write_bytes(png_bytes(seed=1))  # same bytes as a.png
    (src / "broken.png").write_bytes(b"not an image")
    (src / "notes.txt").write_text("ignored")

    db, s = _db()
    r = import_folder(db, s, src, collection="Imported", tags=["old"])
    assert (r.added, r.duplicates, len(r.skipped)) == (2, 1, 1)
    assert "broken.png" in r.skipped[0][0]
    # originals untouched
    assert (src / "a.png").exists() and (src / "broken.png").exists()

    items = client.get("/api/items").json()["items"]
    assert len(items) == 2 and all("old" in [t["name"] for t in i["tags"]] for i in items)
    assert items[0]["source"] == "import"
    assert client.get("/api/collections").json()[0]["count"] == 2

    again = import_folder(db, s, src, collection="Imported")
    assert (again.added, again.duplicates) == (0, 3)


def test_gc_removes_purged_items_and_orphans(client):
    item = client.post("/api/ingest", params={"commit": "true"},
                       files={"file": ("a.png", png_bytes())}).json()["item"]
    keep = client.post("/api/ingest", params={"commit": "true"},
                       files={"file": ("b.png", png_bytes(seed=2))}).json()["item"]
    client.delete(f"/api/items/{item['id']}")

    db, s = _db()
    # Not old enough yet: nothing is purged, nothing is orphaned.
    r = gc(db, s, purge_deleted_days=30)
    assert r.purged_items == 0 and r.orphan_blobs == 0

    old = (datetime.now(UTC) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    db.execute("UPDATE items SET deleted_at = ? WHERE id = ?", (old, item["id"]))
    dry = gc(db, s, purge_deleted_days=30, dry_run=True)
    assert dry.purged_items == 1 and db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2

    real = gc(db, s, purge_deleted_days=30)
    assert real.purged_items == 1 and real.orphan_blobs == 1 and real.orphan_derived == 1
    assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    assert client.get(keep["urls"]["original"]).status_code == 200
    # Running it again finds nothing.
    again = gc(db, s, purge_deleted_days=30)
    assert (again.purged_items, again.orphan_blobs, again.orphan_derived) == (0, 0, 0)
