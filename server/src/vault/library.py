"""Domain operations on items, tags and collections. Callers own the transaction (see db.util.tx)."""
import re
import sqlite3

from vault.db.util import bump_rev

ITEM_COLS = (
    "id, sha256, title, kind, mime, width, height, duration_ms, frame_count, has_alpha, has_audio, "
    "bytes, favorite, source, source_id, source_url, created_at, updated_at, deleted_at, rev"
)


def norm_tag(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())[:40]


def norm_tags(names) -> list[str]:
    seen: dict[str, None] = {}
    for n in names or []:
        t = norm_tag(str(n))
        if t:
            seen[t] = None
    return list(seen)


def item_dicts(db: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict]:
    """Rows from `SELECT ITEM_COLS FROM items` to API dicts, loading tags and collections in bulk."""
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    marks = ",".join("?" * len(ids))
    tags: dict[int, list[dict]] = {i: [] for i in ids}
    for r in db.execute(
        f"SELECT it.item_id, t.name, it.origin, it.score FROM item_tags it "
        f"JOIN tags t ON t.id = it.tag_id WHERE it.item_id IN ({marks}) ORDER BY t.name",
        ids,
    ):
        tags[r["item_id"]].append({"name": r["name"], "origin": r["origin"], "score": r["score"]})
    colls: dict[int, list[int]] = {i: [] for i in ids}
    for r in db.execute(
        f"SELECT ci.item_id, ci.collection_id FROM collection_items ci "
        f"JOIN collections c ON c.id = ci.collection_id AND c.deleted_at IS NULL "
        f"WHERE ci.item_id IN ({marks})",
        ids,
    ):
        colls[r["item_id"]].append(r["collection_id"])
    renditions: dict[int, dict[str, dict]] = {i: {} for i in ids}
    for r in db.execute(
        f"SELECT item_id, kind, bytes, width, height FROM renditions "
        f"WHERE status = 'ready' AND item_id IN ({marks})",
        ids,
    ):
        renditions[r["item_id"]][r["kind"]] = {"bytes": r["bytes"], "width": r["width"], "height": r["height"]}
    out = []
    for r in rows:
        i = r["id"]
        rend = renditions[i]
        urls = {"original": f"/media/{i}/original"}
        if "thumb" in rend:
            urls["thumb"] = f"/media/{i}/thumb"
        if "preview" in rend:
            urls["preview"] = f"/media/{i}/preview"
        for k in ("mp4", "gif"):
            if k in rend:
                urls[k] = f"/media/{i}/send/{k}"
        out.append({
            "id": i,
            "sha256": r["sha256"],
            "title": r["title"],
            "kind": r["kind"],
            "mime": r["mime"],
            "width": r["width"],
            "height": r["height"],
            "duration_ms": r["duration_ms"],
            "frame_count": r["frame_count"],
            "has_alpha": bool(r["has_alpha"]),
            "has_audio": bool(r["has_audio"]),
            "bytes": r["bytes"],
            "favorite": bool(r["favorite"]),
            "source": r["source"],
            "source_url": r["source_url"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "rev": r["rev"],
            "tags": tags[i],
            "collection_ids": sorted(colls[i]),
            "renditions": rend,
            "urls": urls,
        })
    return out


def get_item(db: sqlite3.Connection, item_id: int, include_deleted: bool = False) -> dict | None:
    where = "id = ?" if include_deleted else "id = ? AND deleted_at IS NULL"
    row = db.execute(f"SELECT {ITEM_COLS} FROM items WHERE {where}", (item_id,)).fetchone()
    return item_dicts(db, [row])[0] if row else None


def find_by_sha(db: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    return db.execute(f"SELECT {ITEM_COLS} FROM items WHERE sha256 = ?", (sha256,)).fetchone()


def reindex(db: sqlite3.Connection, item_id: int) -> None:
    row = db.execute("SELECT title, source, deleted_at FROM items WHERE id = ?", (item_id,)).fetchone()
    db.execute("DELETE FROM items_fts WHERE rowid = ?", (item_id,))
    if row is None or row["deleted_at"] is not None:
        return
    names = [r[0] for r in db.execute(
        "SELECT t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE it.item_id = ?", (item_id,)
    )]
    db.execute(
        "INSERT INTO items_fts (rowid, title, tags, source) VALUES (?, ?, ?, ?)",
        (item_id, row["title"], " ".join(names), row["source"]),
    )


def _tag_id(db: sqlite3.Connection, name: str) -> int:
    db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
    return db.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]


def add_tags(db, item_id: int, names, origin: str = "manual", scores: dict[str, float] | None = None) -> None:
    for name in norm_tags(names):
        tid = _tag_id(db, name)
        db.execute(
            "INSERT INTO item_tags (item_id, tag_id, origin, score) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (item_id, tag_id) DO UPDATE SET "
            "origin = CASE WHEN item_tags.origin = 'manual' THEN 'manual' ELSE excluded.origin END",
            (item_id, tid, origin, (scores or {}).get(name)),
        )


def replace_tags(db, item_id: int, names) -> None:
    """The caller's tag list becomes the item's tag set: listed tags are manual, the rest are removed."""
    wanted = norm_tags(names)
    db.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
    add_tags(db, item_id, wanted, "manual")


def valid_collection_ids(db, ids) -> list[int]:
    ids = sorted({int(i) for i in ids or []})
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [r[0] for r in db.execute(
        f"SELECT id FROM collections WHERE deleted_at IS NULL AND id IN ({marks})", ids
    )]


def set_collections(db, item_id: int, ids) -> None:
    db.execute("DELETE FROM collection_items WHERE item_id = ?", (item_id,))
    for cid in valid_collection_ids(db, ids):
        db.execute("INSERT INTO collection_items (collection_id, item_id) VALUES (?, ?)", (cid, item_id))


def create_item(db, meta: dict, *, sha256: str, size: int, title: str, tags, collection_ids,
                auto_tags: dict[str, float] | None = None) -> int:
    """Insert (or resurrect a deleted) item. Must run inside tx()."""
    rev = bump_rev(db)
    existing = find_by_sha(db, sha256)
    cols = dict(
        title=title, kind=meta["kind"], mime=meta["mime"], width=meta["width"], height=meta["height"],
        duration_ms=meta.get("duration_ms"), frame_count=meta.get("frame_count"),
        has_alpha=int(bool(meta.get("has_alpha"))), has_audio=int(bool(meta.get("has_audio"))),
        bytes=size, phash=meta.get("phash"), source=meta.get("source", "upload"),
        source_id=meta.get("source_id"), source_url=meta.get("source_url"),
    )
    if existing is not None:
        item_id = existing["id"]
        sets = ", ".join(f"{k} = ?" for k in cols)
        db.execute(
            f"UPDATE items SET {sets}, deleted_at = NULL, rev = ?, "
            f"updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
            f"created_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (*cols.values(), rev, item_id),
        )
        db.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
    else:
        names = ", ".join(cols)
        marks = ", ".join("?" * len(cols))
        cur = db.execute(
            f"INSERT INTO items (sha256, {names}, rev) VALUES (?, {marks}, ?)",
            (sha256, *cols.values(), rev),
        )
        item_id = cur.lastrowid
    add_tags(db, item_id, tags, "manual")
    if auto_tags:
        add_tags(db, item_id, list(auto_tags), "auto", auto_tags)
    set_collections(db, item_id, collection_ids)
    reindex(db, item_id)
    return item_id
