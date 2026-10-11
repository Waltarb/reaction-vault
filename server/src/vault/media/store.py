import os
from pathlib import Path

from vault.config import Settings


def blob_path(settings: Settings, sha256: str) -> Path:
    return settings.blobs_dir / sha256[:2] / sha256[2:4] / sha256


def derived_path(settings: Settings, sha256: str, name: str) -> Path:
    return settings.derived_dir / sha256[:2] / sha256[2:4] / sha256 / name


def put_blob(settings: Settings, src: Path, sha256: str) -> Path:
    """Move a staged file into the content-addressed store. Same hash means same bytes, so keep one."""
    dest = blob_path(settings, sha256)
    if dest.exists():
        src.unlink(missing_ok=True)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dest)
    return dest
