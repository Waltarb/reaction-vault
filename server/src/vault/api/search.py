import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from vault import library
from vault.api.deps import get_db
from vault.ml.registry import get_embedder, status, table_name
from vault.search import hybrid, index
from vault.search.filters import build_filters

router = APIRouter(prefix="/api", tags=["search"])

KIND = "^(image|animated|video|static)$"


def _in_order(db: sqlite3.Connection, ranked: list[tuple[int, float]]) -> list[dict]:
    if not ranked:
        return []
    ids = [i for i, _ in ranked]
    rows = db.execute(
        f"SELECT {library.ITEM_COLS} FROM items WHERE id IN ({','.join('?' * len(ids))})", ids
    ).fetchall()
    by_id = {d["id"]: d for d in library.item_dicts(db, rows)}
    return [by_id[i] | {"score": round(s, 4)} for i, s in ranked if i in by_id]


@router.get("/search")
def search(
    q: str = Query(min_length=1, max_length=200),
    kind: str | None = Query(default=None, pattern=KIND),
    favorite: bool | None = None,
    unsorted: bool | None = None,
    collection: int | None = None,
    tag: str | None = None,
    max_bytes: int | None = None,
    transparent: bool | None = None,
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1000),
    db: sqlite3.Connection = Depends(get_db),
):
    where, params = build_filters(
        kind=kind, favorite=favorite, unsorted=unsorted, collection=collection, tag=tag,
        max_bytes=max_bytes, transparent=transparent,
    )
    ranked, semantic = hybrid.search(db, get_embedder(), q.strip(), where, params, limit, offset)
    return {"items": _in_order(db, ranked), "semantic": semantic, "offset": offset}


@router.get("/items/{item_id}/similar")
def similar(item_id: int, limit: int = Query(default=12, ge=1, le=60),
            db: sqlite3.Connection = Depends(get_db)):
    """'More like this': nearest items by embedding. Empty until the item has been embedded."""
    if library.get_item(db, item_id) is None:
        raise HTTPException(404, "item not found")
    emb = get_embedder()
    if emb is None:
        return {"items": [], "semantic": False}
    table = table_name(emb.key)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is None:
        return {"items": [], "semantic": False}
    vec = index.get_vec(db, table, item_id)
    if vec is None:
        return {"items": [], "semantic": True}
    where, params = build_filters()
    hits = index.nearest(db, table, vec, where, params, limit, exclude_id=item_id)
    return {"items": _in_order(db, hits), "semantic": True}


@router.get("/embeddings/status")
def embedding_status(db: sqlite3.Connection = Depends(get_db)):
    st = status()
    emb = get_embedder()
    missing = None
    if emb is not None and db.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ?", (table_name(emb.key),)
    ).fetchone():
        missing = len(index.missing_ids(db, table_name(emb.key)))
    return st | {"items_without_vector": missing}
