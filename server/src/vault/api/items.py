import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from vault import library
from vault.api.deps import get_db
from vault.db.util import bump_rev, tx
from vault.search.filters import build_filters

router = APIRouter(prefix="/api", tags=["items"])


class ItemPatch(BaseModel):
    title: str | None = None
    favorite: bool | None = None
    tags: list[str] | None = None
    collection_ids: list[int] | None = None


class CollectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str | None = Field(default=None, max_length=16)


@router.get("/items")
def list_items(
    kind: str | None = Query(default=None, pattern="^(image|animated|video|static)$"),
    favorite: bool | None = None,
    unsorted: bool | None = None,
    collection: int | None = None,
    tag: str | None = None,
    max_bytes: int | None = None,
    transparent: bool | None = None,
    limit: int = Query(default=60, ge=1, le=200),
    cursor: int | None = None,
    db: sqlite3.Connection = Depends(get_db),
):
    where, params = build_filters(
        kind=kind, favorite=favorite, unsorted=unsorted, collection=collection, tag=tag,
        max_bytes=max_bytes, transparent=transparent,
    )
    if cursor is not None:
        where.append("i.id < ?")
        params.append(cursor)
    rows = db.execute(
        f"SELECT {', '.join('i.' + c.strip() for c in library.ITEM_COLS.split(','))} FROM items i "
        f"WHERE {' AND '.join(where)} ORDER BY i.id DESC LIMIT ?",
        (*params, limit + 1),
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": library.item_dicts(db, rows),
        "next_cursor": rows[-1]["id"] if more and rows else None,
    }


@router.get("/items/{item_id}")
def get_item(item_id: int, db: sqlite3.Connection = Depends(get_db)):
    item = library.get_item(db, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return item


@router.patch("/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, db: sqlite3.Connection = Depends(get_db)):
    if library.get_item(db, item_id) is None:
        raise HTTPException(404, "item not found")
    with tx(db):
        rev = bump_rev(db)
        if body.title is not None:
            db.execute("UPDATE items SET title = ? WHERE id = ?", (body.title.strip()[:200], item_id))
        if body.favorite is not None:
            db.execute("UPDATE items SET favorite = ? WHERE id = ?", (int(body.favorite), item_id))
        if body.tags is not None:
            library.replace_tags(db, item_id, body.tags)
        if body.collection_ids is not None:
            library.set_collections(db, item_id, body.collection_ids)
        db.execute(
            "UPDATE items SET rev = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (rev, item_id),
        )
        library.reindex(db, item_id)
    return library.get_item(db, item_id)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Soft delete: a tombstone stays so clients drop the item on their next sync."""
    if library.get_item(db, item_id) is None:
        raise HTTPException(404, "item not found")
    with tx(db):
        rev = bump_rev(db)
        db.execute(
            "UPDATE items SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), rev = ? WHERE id = ?",
            (rev, item_id),
        )
        library.reindex(db, item_id)


@router.get("/tags")
def list_tags(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        "SELECT t.name, COUNT(*) AS n FROM tags t JOIN item_tags it ON it.tag_id = t.id "
        "JOIN items i ON i.id = it.item_id AND i.deleted_at IS NULL GROUP BY t.id ORDER BY n DESC, t.name"
    ).fetchall()
    return [{"name": r["name"], "count": r["n"]} for r in rows]


def _collection(db, cid: int) -> dict | None:
    r = db.execute(
        "SELECT c.id, c.name, c.color, c.rev, "
        "(SELECT COUNT(*) FROM collection_items ci JOIN items i ON i.id = ci.item_id "
        " AND i.deleted_at IS NULL WHERE ci.collection_id = c.id) AS n "
        "FROM collections c WHERE c.id = ? AND c.deleted_at IS NULL",
        (cid,),
    ).fetchone()
    return None if r is None else {"id": r["id"], "name": r["name"], "color": r["color"],
                                   "count": r["n"], "rev": r["rev"]}


@router.get("/collections")
def list_collections(db: sqlite3.Connection = Depends(get_db)):
    ids = [r[0] for r in db.execute("SELECT id FROM collections WHERE deleted_at IS NULL ORDER BY name")]
    return [_collection(db, i) for i in ids]


@router.post("/collections", status_code=201)
def create_collection(body: CollectionBody, db: sqlite3.Connection = Depends(get_db)):
    name = body.name.strip()
    if db.execute("SELECT 1 FROM collections WHERE name = ? AND deleted_at IS NULL", (name,)).fetchone():
        raise HTTPException(409, "a collection with that name exists")
    with tx(db):
        rev = bump_rev(db)
        # A deleted collection keeps its (unique) name; free it so the name can be reused.
        db.execute("UPDATE collections SET name = name || ' #' || id WHERE name = ? AND deleted_at IS NOT NULL",
                   (name,))
        cur = db.execute("INSERT INTO collections (name, color, rev) VALUES (?, ?, ?)",
                         (name, body.color, rev))
    return _collection(db, cur.lastrowid)


@router.patch("/collections/{cid}")
def rename_collection(cid: int, body: CollectionBody, db: sqlite3.Connection = Depends(get_db)):
    if _collection(db, cid) is None:
        raise HTTPException(404, "collection not found")
    try:
        with tx(db):
            rev = bump_rev(db)
            db.execute("UPDATE collections SET name = ?, color = ?, rev = ? WHERE id = ?",
                       (body.name.strip(), body.color, rev, cid))
    except sqlite3.IntegrityError as e:
        raise HTTPException(409, "a collection with that name exists") from e
    return _collection(db, cid)


@router.delete("/collections/{cid}", status_code=204)
def delete_collection(cid: int, db: sqlite3.Connection = Depends(get_db)):
    if _collection(db, cid) is None:
        raise HTTPException(404, "collection not found")
    with tx(db):
        rev = bump_rev(db)
        # Members change, so bump their revs and clients refetch their collection_ids.
        db.execute(
            "UPDATE items SET rev = ? WHERE id IN (SELECT item_id FROM collection_items WHERE collection_id = ?)",
            (rev, cid),
        )
        db.execute("DELETE FROM collection_items WHERE collection_id = ?", (cid,))
        db.execute("UPDATE collections SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), rev = ? "
                   "WHERE id = ?", (rev, cid))
