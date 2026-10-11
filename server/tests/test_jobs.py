import shutil

import pytest

from vault.config import get_settings
from vault.db.connection import connect
from vault.jobs import queue, tasks

from conftest import gif_bytes, webp_anim_bytes

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def add(client, data, name):
    r = client.post("/api/ingest", params={"commit": "true"}, files={"file": (name, data)})
    assert r.status_code == 200, r.text
    return r.json()["item"]


def test_commit_queues_renditions_only_for_animated(client):
    from conftest import png_bytes

    add(client, png_bytes(), "a.png")
    add(client, gif_bytes(), "b.gif")
    db = connect(get_settings().db_path)
    rows = db.execute("SELECT type, item_id FROM jobs WHERE status = 'queued' ORDER BY id").fetchall()
    assert [r["item_id"] for r in rows if r["type"] == "renditions"] == [2]  # the gif, not the png
    # Embeddings are switched off in tests, so nothing waits for a model that will never load.
    assert [r for r in rows if r["type"] == "embed"] == []
    db.close()


def test_failed_job_is_retried_then_marked_failed():
    from vault.db.migrate import migrate

    db = connect(":memory:")
    migrate(db)
    queue.enqueue(db, "boom", None)
    queue.enqueue(db, "boom", None)  # duplicate while queued is ignored
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1

    def boom(db, job):
        raise RuntimeError("nope")

    for attempt in range(1, queue.MAX_ATTEMPTS + 1):
        db.execute("UPDATE jobs SET run_after = '1970-01-01T00:00:00.000Z' WHERE status = 'queued'")
        assert queue.run_pending(db, {"boom": boom}) == 1
        row = db.execute("SELECT status, attempts, error FROM jobs").fetchone()
        assert row["attempts"] == attempt and "nope" in row["error"]
    assert row["status"] == "failed"


def test_gif_send_is_passthrough_without_ffmpeg(client):
    item = add(client, gif_bytes(), "b.gif")
    r = client.get(f"/media/{item['id']}/send/gif")
    assert r.status_code == 200 and r.content == gif_bytes()
    assert client.get(f"/media/{item['id']}/send/nope").status_code == 404
    got = client.get(f"/api/items/{item['id']}").json()
    assert got["renditions"]["gif"]["bytes"] == len(gif_bytes())


def test_still_images_have_no_send_formats(client):
    from conftest import png_bytes

    item = add(client, png_bytes(), "a.png")
    assert client.get(f"/media/{item['id']}/send/mp4").status_code == 404


@needs_ffmpeg
def test_animated_webp_converts_to_mp4_and_gif(client):
    item = add(client, webp_anim_bytes(frames=6), "b.webp")
    db = connect(get_settings().db_path)
    assert queue.run_pending(db, tasks.HANDLERS) == 1
    db.close()

    got = client.get(f"/api/items/{item['id']}").json()
    assert got["renditions"]["mp4"]["bytes"] > 0 and got["renditions"]["gif"]["bytes"] > 0
    assert got["rev"] > item["rev"]
    mp4 = client.get(f"/media/{item['id']}/send/mp4")
    assert mp4.status_code == 200 and mp4.headers["content-type"] == "video/mp4"
    assert mp4.content[4:8] == b"ftyp"
    gif = client.get(f"/media/{item['id']}/send/gif")
    assert gif.content[:6] in (b"GIF87a", b"GIF89a")


def test_send_reports_503_when_ffmpeg_is_missing(client, monkeypatch):
    monkeypatch.setattr("vault.media.convert.shutil.which", lambda _name: None)
    item = add(client, webp_anim_bytes(), "b.webp")
    assert client.get(f"/media/{item['id']}/send/mp4").status_code == 503


def test_deferred_job_waits_without_using_an_attempt():
    from vault.db.migrate import migrate

    db = connect(":memory:")
    migrate(db)
    queue.enqueue(db, "later", None)

    def later(db, job):
        raise queue.Deferred(60)

    assert queue.run_pending(db, {"later": later}) == 1
    row = db.execute("SELECT status, attempts FROM jobs").fetchone()
    assert (row["status"], row["attempts"]) == ("queued", 0)
    assert queue.claim(db) is None  # not due yet
