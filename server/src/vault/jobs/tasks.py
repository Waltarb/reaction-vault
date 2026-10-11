import logging
import sqlite3
import threading

from vault.config import Settings, get_settings
from vault.db.util import bump_rev, tx
from vault.jobs.queue import Deferred, enqueue
from vault.media import convert
from vault.media.probe import probe
from vault.media.store import blob_path, derived_path
from vault.ml import registry
from vault.ml.service import embed_file
from vault.search import index

log = logging.getLogger("vault.jobs")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_backfilled: set[str] = set()

# A send format is served straight from the original when it already is that format.
PASSTHROUGH = {"gif": "image/gif", "mp4": "video/mp4"}
FILENAME = {"mp4": "send.mp4", "gif": "send.gif"}


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def sendable(item: sqlite3.Row) -> bool:
    return item["kind"] in ("animated", "video")


def ensure_rendition(db: sqlite3.Connection, settings: Settings, item: sqlite3.Row, fmt: str):
    """Path of a send rendition, built first if needed. Raises convert.ConvertError."""
    if item["mime"] == PASSTHROUGH[fmt]:
        with tx(db):  # sizes in "Send as" should list the original's format too
            db.execute(
                "INSERT OR REPLACE INTO renditions (item_id, kind, bytes, width, height, status) "
                "VALUES (?, ?, ?, ?, ?, 'ready')",
                (item["id"], fmt, item["bytes"], item["width"], item["height"]),
            )
        return blob_path(settings, item["sha256"])
    dest = derived_path(settings, item["sha256"], FILENAME[fmt])
    with _lock_for(f"{item['sha256']}:{fmt}"):
        if not dest.exists():
            src = blob_path(settings, item["sha256"])
            (convert.to_mp4 if fmt == "mp4" else convert.to_gif)(src, dest, item["kind"])
        info = probe(dest)
        with tx(db):
            db.execute(
                "INSERT OR REPLACE INTO renditions (item_id, kind, bytes, width, height, status) "
                "VALUES (?, ?, ?, ?, ?, 'ready')",
                (item["id"], fmt, dest.stat().st_size, info.width, info.height),
            )
    return dest


def renditions(db: sqlite3.Connection, job: sqlite3.Row) -> None:
    item = db.execute(
        "SELECT * FROM items WHERE id = ? AND deleted_at IS NULL", (job["item_id"],)
    ).fetchone()
    if item is None or not sendable(item):
        return
    settings = get_settings()
    for fmt in ("mp4", "gif"):
        ensure_rendition(db, settings, item, fmt)
    with tx(db):  # clients learn the new sizes through the sync feed
        db.execute("UPDATE items SET rev = ? WHERE id = ?", (bump_rev(db), item["id"]))


def embed(db: sqlite3.Connection, job: sqlite3.Row) -> None:
    emb = registry.get_embedder()
    if emb is None:
        raise Deferred(60)  # model still loading (or switched off); try again later
    item = db.execute(
        "SELECT * FROM items WHERE id = ? AND deleted_at IS NULL", (job["item_id"],)
    ).fetchone()
    if item is None:
        return
    vec = embed_file(blob_path(get_settings(), item["sha256"]), item["kind"], item["duration_ms"], emb)
    if vec is None:
        raise RuntimeError("could not embed file")
    with tx(db):
        index.upsert(db, index.ensure_table(db, emb.key, emb.dim), item["id"], vec)


HANDLERS = {"renditions": renditions, "embed": embed}


def backfill_embeddings(db: sqlite3.Connection) -> None:
    """Idle hook: once a model is ready, queue every item that has no vector yet (once per model)."""
    emb = registry.get_embedder()
    if emb is None or emb.key in _backfilled:
        return
    table = index.ensure_table(db, emb.key, emb.dim)
    ids = index.missing_ids(db, table)
    with tx(db):
        for item_id in ids:
            enqueue(db, "embed", item_id)
    _backfilled.add(emb.key)
    if ids:
        log.info("queued %d items for embedding", len(ids))
