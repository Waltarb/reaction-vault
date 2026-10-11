import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from vault.api.deps import get_db
from vault.config import Settings, get_settings
from vault.media.store import blob_path, derived_path

router = APIRouter(prefix="/media", tags=["media"])

# Content-addressed, so a URL's bytes never change.
CACHE = {"Cache-Control": "private, max-age=31536000, immutable"}


def _item(db: sqlite3.Connection, item_id: int):
    row = db.execute(
        "SELECT sha256, mime FROM items WHERE id = ? AND deleted_at IS NULL", (item_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "item not found")
    return row


def _file(path, media_type: str, sha: str):
    if not path.exists():
        raise HTTPException(404, "file not available")
    return FileResponse(path, media_type=media_type, headers={**CACHE, "ETag": f'"{sha}"'})


@router.get("/{item_id}/original")
def original(item_id: int, db: sqlite3.Connection = Depends(get_db),
             settings: Settings = Depends(get_settings)):
    row = _item(db, item_id)
    return _file(blob_path(settings, row["sha256"]), row["mime"], row["sha256"])


@router.get("/{item_id}/thumb")
def thumb(item_id: int, db: sqlite3.Connection = Depends(get_db),
          settings: Settings = Depends(get_settings)):
    row = _item(db, item_id)
    return _file(derived_path(settings, row["sha256"], "thumb.webp"), "image/webp", row["sha256"])


@router.get("/{item_id}/preview")
def preview(item_id: int, db: sqlite3.Connection = Depends(get_db),
            settings: Settings = Depends(get_settings)):
    row = _item(db, item_id)
    return _file(derived_path(settings, row["sha256"], "preview.webp"), "image/webp", row["sha256"])
