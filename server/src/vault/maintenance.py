"""Bulk import and garbage collection, used by the CLI."""
import hashlib
import shutil
import sqlite3
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from vault import library
from vault.api.ingest import CommitBody, commit_staged, stage_file
from vault.config import Settings
from vault.db.util import bump_rev, tx
from vault.ml.registry import table_name

MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".mp4", ".webm", ".mov", ".bmp"}


@dataclass
class ImportReport:
    added: int = 0
    duplicates: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _files(folder: Path, recursive: bool) -> Iterable[Path]:
    walker = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in walker if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES)


def import_folder(
    db: sqlite3.Connection, settings: Settings, folder: Path, *, recursive: bool = True,
    collection: str | None = None, tags: list[str] | None = None,
    progress: Callable[[int, int, Path], None] | None = None,
) -> ImportReport:
    """Add every media file under `folder`. Originals are copied, never moved or modified."""
    settings.ensure_dirs()
    report = ImportReport()
    collection_ids: list[int] = []
    if collection:
        with tx(db):
            row = db.execute(
                "SELECT id FROM collections WHERE name = ? AND deleted_at IS NULL", (collection,)
            ).fetchone()
            if row is None:
                cur = db.execute("INSERT INTO collections (name, rev) VALUES (?, ?)", (collection, bump_rev(db)))
                collection_ids = [cur.lastrowid]
            else:
                collection_ids = [row["id"]]

    files = list(_files(folder, recursive))
    for n, src in enumerate(files, 1):
        if progress:
            progress(n, len(files), src)
        part = settings.staging_dir / f"{uuid.uuid4().hex}.part"
        try:
            h = hashlib.sha256()
            with open(src, "rb") as fin, open(part, "wb") as out:
                while chunk := fin.read(1 << 20):
                    h.update(chunk)
                    out.write(chunk)
            if part.stat().st_size == 0 or part.stat().st_size > settings.max_upload_bytes:
                part.unlink(missing_ok=True)
                report.skipped.append((str(src), "empty or too large"))
                continue
            stage_id, meta = stage_file(
                db, settings, part, h.hexdigest(), name=src.name, source="import", source_url=None,
            )
            if stage_id is None:
                report.duplicates += 1
                continue
            res = commit_staged(db, settings, stage_id, CommitBody(tags=tags, collection_ids=collection_ids))
            if res["duplicate"]:
                report.duplicates += 1
            else:
                report.added += 1
        except HTTPException as e:
            part.unlink(missing_ok=True)
            report.skipped.append((str(src), str(e.detail)))
        except Exception as e:  # one bad file must not stop a 10,000 file import
            part.unlink(missing_ok=True)
            report.skipped.append((str(src), f"{type(e).__name__}: {e}"))
    return report


@dataclass
class GcReport:
    purged_items: int = 0
    orphan_blobs: int = 0
    orphan_derived: int = 0
    stale_staging: int = 0
    old_jobs: int = 0
    bytes_freed: int = 0


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def gc(db: sqlite3.Connection, settings: Settings, *, purge_deleted_days: int | None = 30,
       dry_run: bool = False) -> GcReport:
    """Remove files and rows nothing refers to. Tombstones older than `purge_deleted_days` go for good.

    A purged item loses its tombstone, so a client that has not synced for longer than that keeps
    the item until it does a full resync.
    """
    report = GcReport()
    now = datetime.now(UTC)

    def remove(path: Path) -> None:
        report.bytes_freed += _size(path)
        if not dry_run:
            shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)

    if purge_deleted_days is not None:
        cutoff = (now - timedelta(days=purge_deleted_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        old = db.execute(
            "SELECT id FROM items WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,)
        ).fetchall()
        report.purged_items = len(old)
        if old and not dry_run:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'vec\\_%' ESCAPE '\\'")
                      if r[0] in {table_name(m[0]) for m in db.execute("SELECT key FROM embedding_models")}]
            with tx(db):
                for r in old:
                    for t in tables:
                        db.execute(f"DELETE FROM {t} WHERE item_id = ?", (r["id"],))
                    db.execute("DELETE FROM items_fts WHERE rowid = ?", (r["id"],))
                    db.execute("DELETE FROM items WHERE id = ?", (r["id"],))

    keep = {r[0] for r in db.execute("SELECT sha256 FROM items")}
    for root, counter in ((settings.blobs_dir, "orphan_blobs"), (settings.derived_dir, "orphan_derived")):
        if not root.exists():
            continue
        for a in root.iterdir():
            for b in a.iterdir() if a.is_dir() else []:
                for entry in b.iterdir() if b.is_dir() else []:
                    if entry.name not in keep:
                        remove(entry)
                        setattr(report, counter, getattr(report, counter) + 1)

    staged_ids = {r[0] for r in db.execute("SELECT id FROM staged")}
    for f in settings.staging_dir.glob("*") if settings.staging_dir.exists() else []:
        age = now - datetime.fromtimestamp(f.stat().st_mtime, UTC)
        if f.stem not in staged_ids and age > timedelta(hours=1):
            remove(f)
            report.stale_staging += 1

    old_cut = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    report.old_jobs = db.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('done', 'failed') AND run_after < ?", (old_cut,)
    ).fetchone()[0]
    if not dry_run:
        with tx(db):
            db.execute("DELETE FROM jobs WHERE status IN ('done', 'failed') AND run_after < ?", (old_cut,))
    return report
