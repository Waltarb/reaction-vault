import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from PIL import Image
from pydantic import BaseModel, Field

from vault import library
from vault.api.deps import get_db
from vault.api.ingest import CommitBody, commit_staged, stage_file
from vault.config import Settings, get_settings
from vault.db.util import tx
from vault.media import fetch
from vault.ml.registry import get_embedder, table_name
from vault.ml.service import embed_file
from vault.plugins import registry
from vault.plugins.base import Candidate
from vault.search import index

log = logging.getLogger("vault.discover")

router = APIRouter(prefix="/api/discover", tags=["discover"])

RERANK_LIMIT = 60  # candidates embedded per request


class SaveBody(BaseModel):
    source: str
    source_id: str = Field(min_length=1, max_length=128)
    tags: list[str] | None = None
    collection_ids: list[int] = Field(default_factory=list)


def _saved_map(db: sqlite3.Connection, cands: list[Candidate]) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for source in {c.source for c in cands}:
        ids = [c.source_id for c in cands if c.source == source]
        marks = ",".join("?" * len(ids))
        for r in db.execute(
            f"SELECT id, source_id FROM items WHERE deleted_at IS NULL AND source = ? "
            f"AND source_id IN ({marks})", (source, *ids),
        ):
            out[(source, r["source_id"])] = r["id"]
    return out


def _picked_vector(db: sqlite3.Connection, ids: list[int]) -> np.ndarray | None:
    emb = get_embedder()
    if emb is None or not ids:
        return None
    table = table_name(emb.key)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is None:
        return None
    vecs = [v for i in ids if (v := index.get_vec(db, table, i)) is not None]
    if not vecs:
        return None
    mean = np.mean(vecs, axis=0)
    return mean / max(float(np.linalg.norm(mean)), 1e-12)


def _candidate_vec(settings: Settings, cand: Candidate, emb) -> np.ndarray | None:
    """Download a candidate's small preview into staging and embed it."""
    try:
        path, _sha, _name, _url = fetch.download(cand.preview_url, settings.staging_dir, 5 * 1024 * 1024)
    except Exception as e:
        log.info("preview fetch failed for %s: %s", cand.source_id, e)
        return None
    try:
        with Image.open(path) as im:
            kind = "animated" if getattr(im, "n_frames", 1) > 1 else "image"
        return embed_file(path, kind, None, emb)
    except Exception as e:
        log.info("preview embed failed for %s: %s", cand.source_id, e)
        return None
    finally:
        path.unlink(missing_ok=True)


def _rerank(db, settings, cands: list[Candidate], target: np.ndarray) -> dict[tuple[str, str], float]:
    """Cosine similarity of each candidate's preview to the picked items. Embeddings are cached."""
    emb = get_embedder()
    key = emb.key
    sims: dict[tuple[str, str], float] = {}
    todo: list[Candidate] = []
    for c in cands[:RERANK_LIMIT]:
        row = db.execute(
            "SELECT embedding FROM discover_vecs WHERE source = ? AND source_id = ? AND model = ?",
            (c.source, c.source_id, key),
        ).fetchone()
        if row:
            sims[(c.source, c.source_id)] = float(np.frombuffer(row[0], dtype=np.float32) @ target)
        else:
            todo.append(c)
    if todo:
        with ThreadPoolExecutor(max_workers=4) as pool:
            fetched = list(pool.map(lambda c: _candidate_vec(settings, c, emb), todo))
        with tx(db):
            for c, vec in zip(todo, fetched):
                if vec is None:
                    continue
                db.execute(
                    "INSERT OR REPLACE INTO discover_vecs (source, source_id, model, embedding) "
                    "VALUES (?, ?, ?, ?)", (c.source, c.source_id, key, vec.astype(np.float32).tobytes()),
                )
                sims[(c.source, c.source_id)] = float(vec @ target)
    return sims


@router.get("/sources")
def list_sources():
    return [{"key": s.key, "label": s.label} for s in registry.sources().values()]


@router.get("/search")
def search(
    q: str = Query(min_length=1, max_length=200),
    sources: str | None = Query(default=None, description="comma-separated source keys; default all"),
    animated: bool | None = None,
    similar_to: str | None = Query(default=None, description="comma-separated item ids to rank by look"),
    page: int = Query(default=1, ge=1, le=50),
    limit: int = Query(default=24, ge=1, le=48),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    available = registry.sources()
    wanted = [k.strip() for k in sources.split(",")] if sources else list(available)
    unknown = [k for k in wanted if k not in available]
    if unknown:
        raise HTTPException(400, f"unknown source: {unknown[0]}")

    cands: list[Candidate] = []
    errors: dict[str, str] = {}
    has_more = False
    for key in wanted:
        try:
            result = available[key].search(q.strip(), animated=animated, page=page, limit=limit)
        except Exception as e:
            log.warning("discover source %s failed: %s", key, e)
            errors[key] = "unavailable"
            continue
        cands += result.items
        has_more = has_more or result.has_more

    sims: dict[tuple[str, str], float] = {}
    if similar_to:
        try:
            picked = [int(x) for x in similar_to.split(",") if x.strip()][:10]
        except ValueError as e:
            raise HTTPException(400, "similar_to must be item ids") from e
        target = _picked_vector(db, picked)
        if target is not None and cands:
            sims = _rerank(db, settings, cands, target)
            cands.sort(key=lambda c: -sims.get((c.source, c.source_id), -1.0))

    saved = _saved_map(db, cands)
    return {
        "items": [
            c.public() | {
                "saved_item_id": saved.get((c.source, c.source_id)),
                "similarity": round(sims[(c.source, c.source_id)], 3) if (c.source, c.source_id) in sims else None,
            }
            for c in cands
        ],
        "page": page,
        "has_more": has_more,
        "reranked": bool(sims),
        "errors": errors,
    }


@router.post("/save")
def save(body: SaveBody, db: sqlite3.Connection = Depends(get_db),
         settings: Settings = Depends(get_settings)):
    source = registry.sources().get(body.source)
    if source is None:
        raise HTTPException(400, f"unknown source: {body.source}")

    existing = db.execute(
        f"SELECT {library.ITEM_COLS} FROM items WHERE source = ? AND source_id = ? AND deleted_at IS NULL",
        (body.source, body.source_id),
    ).fetchone()
    if existing:
        return {"item": library.item_dicts(db, [existing])[0], "duplicate": "source"}

    try:
        cand = source.resolve(body.source_id)
    except Exception as e:
        log.warning("resolve failed for %s/%s: %s", body.source, body.source_id, e)
        raise HTTPException(502, "source is unavailable") from e
    if cand is None:
        raise HTTPException(404, "not found at the source")

    settings.ensure_dirs()
    try:
        path, sha, _name, _final = fetch.download(cand.file_url, settings.staging_dir, settings.max_upload_bytes)
    except fetch.FetchError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"download failed: {e}") from e

    stage_id, meta = stage_file(
        db, settings, path, sha, name=cand.title, source=cand.source,
        source_url=cand.page_url, source_id=cand.source_id,
    )
    if stage_id is None:  # same bytes already in the vault under another source
        return {"item": meta, "duplicate": "exact"}
    result = commit_staged(
        db, settings, stage_id,
        CommitBody(title=cand.title, tags=body.tags, collection_ids=body.collection_ids),
        source_tags=library.norm_tags([cand.title]) if cand.title else None,
    )
    return result
