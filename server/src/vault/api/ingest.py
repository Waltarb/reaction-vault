import base64
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from vault import library
from vault.api.deps import get_db
from vault.config import Settings, get_settings
from vault.db.util import tx
from vault.media import fetch, thumbs
from vault.media.probe import UnsupportedMedia, hamming, probe
from vault.media.store import derived_path, put_blob
from vault.ml import autotag
from vault.ml.registry import get_embedder
from vault.ml.service import autotag_params, embed_file
from vault.search import index

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

STAGE_TTL = timedelta(hours=24)
NEAR_LIMIT = 5


class CommitBody(BaseModel):
    title: str | None = None
    tags: list[str] | None = None  # None: accept the suggested auto tags as they are
    collection_ids: list[int] = Field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _clean_title(name: str) -> str:
    stem = Path(name).stem if name else ""
    return re.sub(r"[\s_]+", " ", stem).strip()[:120]


def _purge_expired(db: sqlite3.Connection, settings: Settings) -> None:
    rows = db.execute("SELECT id FROM staged WHERE expires_at < ?", (_iso(_now()),)).fetchall()
    for r in rows:
        (settings.staging_dir / f"{r['id']}.bin").unlink(missing_ok=True)
    if rows:
        db.execute("DELETE FROM staged WHERE expires_at < ?", (_iso(_now()),))


def _vec_from_meta(meta: dict) -> np.ndarray | None:
    raw = meta.get("embedding")
    return np.frombuffer(base64.b64decode(raw), dtype=np.float32) if raw else None


def near_matches(db: sqlite3.Connection, settings: Settings, meta: dict, exclude_sha: str) -> list[dict]:
    """Items that look like the staged file: embedding cosine and/or perceptual-hash distance."""
    found: dict[int, float] = {}
    phash = meta.get("phash")
    if phash is not None:
        for r in db.execute(
            "SELECT id, phash FROM items WHERE deleted_at IS NULL AND phash IS NOT NULL AND sha256 != ?",
            (exclude_sha,),
        ):
            d = hamming(phash, r["phash"])
            if d <= settings.near_dup_phash:
                found[r["id"]] = 1 - d / 64
    vec = _vec_from_meta(meta)
    if vec is not None:
        table = index.ensure_table(db, meta["model"], len(vec))
        for item_id, sim in index.nearest(
            db, table, vec, ["i.deleted_at IS NULL", "i.sha256 != ?"], [exclude_sha], NEAR_LIMIT
        ):
            if sim >= settings.near_dup_cosine:
                found[item_id] = max(found.get(item_id, 0.0), sim)
    out = []
    for item_id, sim in sorted(found.items(), key=lambda kv: -kv[1])[:NEAR_LIMIT]:
        item = library.get_item(db, item_id)
        if item:
            out.append({"item": item, "similarity": round(sim, 3)})
    return out


def _stage(db, settings, path: Path, sha: str, *, name: str, source: str, source_url: str | None):
    """Probe a downloaded file and register it as staged. Returns (staged_id, meta) or (None, existing)."""
    try:
        info = probe(path)
    except UnsupportedMedia as e:
        path.unlink(missing_ok=True)
        raise HTTPException(415, f"unsupported media: {e}") from e
    except Exception as e:  # corrupt files raise assorted decoder errors
        path.unlink(missing_ok=True)
        raise HTTPException(422, "could not read this file") from e
    existing = library.find_by_sha(db, sha)
    if existing is not None and existing["deleted_at"] is None:
        path.unlink(missing_ok=True)
        return None, library.item_dicts(db, [existing])[0]
    meta = info.as_dict() | {
        "sha256": sha,
        "bytes": path.stat().st_size,
        "source": source,
        "source_url": source_url,
        "suggested_title": _clean_title(name),
    }
    embedder = get_embedder()
    vec = embed_file(path, info.kind, info.duration_ms, embedder)
    if vec is not None:
        meta["embedding"] = base64.b64encode(vec.tobytes()).decode()
        meta["model"] = embedder.key
        meta["auto_tags"] = autotag.suggest(embedder, settings.models_dir, db, vec, **autotag_params(settings))
    stage_id = uuid.uuid4().hex
    final = settings.staging_dir / f"{stage_id}.bin"
    path.replace(final)
    with tx(db):
        db.execute(
            "INSERT INTO staged (id, sha256, meta_json, expires_at) VALUES (?, ?, ?, ?)",
            (stage_id, sha, json.dumps(meta), _iso(_now() + STAGE_TTL)),
        )
    return stage_id, meta


def commit_staged(db, settings: Settings, stage_id: str, body: CommitBody) -> dict:
    row = db.execute("SELECT * FROM staged WHERE id = ?", (stage_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "staged upload not found or expired")
    meta = json.loads(row["meta_json"])
    sha = row["sha256"]
    staged_file = settings.staging_dir / f"{stage_id}.bin"
    existing = library.find_by_sha(db, sha)
    if existing is not None and existing["deleted_at"] is None:
        with tx(db):
            db.execute("DELETE FROM staged WHERE id = ?", (stage_id,))
        staged_file.unlink(missing_ok=True)
        return {"item": library.item_dicts(db, [existing])[0], "duplicate": "exact"}

    blob = put_blob(settings, staged_file, sha)
    renditions = []
    try:
        w, h = thumbs.make_thumb(blob, derived_path(settings, sha, "thumb.webp"), meta["kind"])
        renditions.append(("thumb", derived_path(settings, sha, "thumb.webp"), w, h))
        if meta["kind"] == "animated":
            size = thumbs.make_preview(blob, derived_path(settings, sha, "preview.webp"))
            if size:
                renditions.append(("preview", derived_path(settings, sha, "preview.webp"), *size))
    except Exception as e:
        raise HTTPException(422, f"could not process this file: {e}") from e

    title = (body.title if body.title is not None else meta.get("suggested_title") or "").strip()[:200]
    suggested: dict[str, float] = meta.get("auto_tags") or {}
    final_tags = library.norm_tags(list(suggested) if body.tags is None else body.tags)
    auto = {t: suggested[t] for t in final_tags if t in suggested}
    vec = _vec_from_meta(meta)
    with tx(db):
        item_id = library.create_item(
            db, meta, sha256=sha, size=meta["bytes"], title=title,
            tags=[t for t in final_tags if t not in auto], collection_ids=body.collection_ids,
            auto_tags=auto,
        )
        if vec is not None:
            index.upsert(db, index.ensure_table(db, meta["model"], len(vec)), item_id, vec)
        for kind, path, w, h in renditions:
            db.execute(
                "INSERT OR REPLACE INTO renditions (item_id, kind, bytes, width, height, status) "
                "VALUES (?, ?, ?, ?, ?, 'ready')",
                (item_id, kind, path.stat().st_size, w, h),
            )
        db.execute("DELETE FROM staged WHERE id = ?", (stage_id,))
    return {"item": library.get_item(db, item_id), "duplicate": None}


@router.post("")
def ingest(
    commit: bool = False,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    title: str | None = Form(default=None),
    source: str = Form(default="upload"),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Stage an upload (multipart `file`) or a remote file (form `url`), or stage and commit at once."""
    if (file is None) == (url is None):
        raise HTTPException(400, "send exactly one of: file, url")
    settings.ensure_dirs()
    with tx(db):
        _purge_expired(db, settings)

    source_url = None
    if file is not None:
        dest = settings.staging_dir / f"{uuid.uuid4().hex}.part"
        h, size = hashlib.sha256(), 0
        try:
            with open(dest, "wb") as out:
                while chunk := file.file.read(65536):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(413, "file is too large")
                    h.update(chunk)
                    out.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        path, sha, name = dest, h.hexdigest(), file.filename or ""
    else:
        try:
            path, sha, name, source_url = fetch.download(url, settings.staging_dir, settings.max_upload_bytes)
        except fetch.FetchError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(502, f"download failed: {e}") from e
        if source == "upload":
            source = "url"

    if path.stat().st_size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(400, "empty file")

    stage_id, meta = _stage(db, settings, path, sha, name=name, source=source, source_url=source_url)
    if stage_id is None:
        return {"staged_id": None, "duplicate": "exact", "item": meta, "near": [], "auto_tags": []}

    if commit:
        result = commit_staged(db, settings, stage_id, CommitBody(title=title))
        return {"staged_id": None, "duplicate": result["duplicate"], "item": result["item"],
                "near": [], "auto_tags": []}

    public = {k: v for k, v in meta.items() if k not in ("embedding", "auto_tags")}
    return {
        "staged_id": stage_id,
        "duplicate": None,
        "meta": public,
        "near": near_matches(db, settings, meta, sha),
        "auto_tags": [{"name": n, "score": s} for n, s in (meta.get("auto_tags") or {}).items()],
        "file_url": f"/api/ingest/{stage_id}/file",
    }


@router.post("/{stage_id}/commit")
def commit(
    stage_id: str,
    body: CommitBody,
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return commit_staged(db, settings, stage_id, body)


@router.get("/{stage_id}/file")
def staged_file(stage_id: str, db: sqlite3.Connection = Depends(get_db),
                settings: Settings = Depends(get_settings)):
    row = db.execute("SELECT meta_json FROM staged WHERE id = ?", (stage_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "staged upload not found or expired")
    meta = json.loads(row["meta_json"])
    return FileResponse(settings.staging_dir / f"{stage_id}.bin", media_type=meta["mime"])


@router.delete("/{stage_id}", status_code=204)
def discard(stage_id: str, db: sqlite3.Connection = Depends(get_db),
            settings: Settings = Depends(get_settings)):
    if not re.fullmatch(r"[0-9a-f]{32}", stage_id):
        raise HTTPException(404, "staged upload not found")
    with tx(db):
        db.execute("DELETE FROM staged WHERE id = ?", (stage_id,))
    (settings.staging_dir / f"{stage_id}.bin").unlink(missing_ok=True)
