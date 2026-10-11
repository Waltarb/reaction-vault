import shutil
import sqlite3

from fastapi import APIRouter, Depends, Query

from vault import __version__, library
from vault.api.deps import get_db
from vault.config import Settings, get_settings
from vault.db.util import current_rev
from vault.ml.registry import status as embedding_status

router = APIRouter(prefix="/api", tags=["sync"])


@router.get("/sync")
def sync(
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    db: sqlite3.Connection = Depends(get_db),
):
    """Everything that changed after revision `since`, oldest change first.

    Clients keep the returned `rev` and send it next time; while `has_more` is true, call again
    immediately. Deleted items and collections appear as tombstones ({id, deleted: true, rev}).
    """
    rows = db.execute(
        f"SELECT {library.ITEM_COLS} FROM items WHERE rev > ? ORDER BY rev, id LIMIT ?", (since, limit + 1)
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    if has_more:
        # Rows sharing a rev are one logical change; never split them across pages.
        last = rows[-1]["rev"]
        trimmed = [r for r in rows if r["rev"] != last]
        rows = trimmed or db.execute(
            f"SELECT {library.ITEM_COLS} FROM items WHERE rev = ? ORDER BY id", (last,)
        ).fetchall()
    live = [r for r in rows if r["deleted_at"] is None]
    by_id = {d["id"]: d for d in library.item_dicts(db, live)}
    items = [
        by_id[r["id"]] if r["deleted_at"] is None else {"id": r["id"], "deleted": True, "rev": r["rev"]}
        for r in rows
    ]
    cursor = rows[-1]["rev"] if rows else since
    upto = cursor if has_more else current_rev(db)

    collections = []
    for c in db.execute(
        "SELECT id, name, color, rev, deleted_at FROM collections WHERE rev > ? AND rev <= ? ORDER BY rev",
        (since, upto),
    ):
        collections.append(
            {"id": c["id"], "deleted": True, "rev": c["rev"]} if c["deleted_at"]
            else {"id": c["id"], "name": c["name"], "color": c["color"], "rev": c["rev"]}
        )
    return {"rev": upto, "has_more": has_more, "items": items, "collections": collections}


@router.get("/server")
def server_info(db: sqlite3.Connection = Depends(get_db), settings: Settings = Depends(get_settings)):
    """What the 'Server' tab and the desktop sidebar card show."""
    total = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS b FROM items WHERE deleted_at IS NULL"
    ).fetchone()
    unsorted = db.execute(
        "SELECT COUNT(*) FROM items i WHERE i.deleted_at IS NULL AND NOT EXISTS ("
        "SELECT 1 FROM collection_items ci JOIN collections c ON c.id = ci.collection_id "
        "AND c.deleted_at IS NULL WHERE ci.item_id = i.id)"
    ).fetchone()[0]
    jobs = {r["status"]: r["n"] for r in db.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}
    disk = shutil.disk_usage(settings.data_dir)
    return {
        "version": __version__,
        "rev": current_rev(db),
        "items": total["n"],
        "bytes": total["b"],
        "unsorted": unsorted,
        "favorites": db.execute(
            "SELECT COUNT(*) FROM items WHERE deleted_at IS NULL AND favorite = 1"
        ).fetchone()[0],
        "jobs": jobs,
        "disk_free": disk.free,
        "embeddings": embedding_status(),
    }
