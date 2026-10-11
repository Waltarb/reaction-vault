import argparse
import sys

from vault.api.deps import hash_token, new_token
from vault.config import get_settings
from vault.db.connection import connect
from vault.db.migrate import migrate


def _db():
    settings = get_settings()
    settings.ensure_dirs()
    db = connect(settings.db_path)
    migrate(db)
    return db


def token_create(name: str) -> int:
    db = _db()
    token = new_token()
    try:
        db.execute("INSERT INTO devices (name, token_hash) VALUES (?, ?)", (name, hash_token(token)))
    except Exception as e:
        print(f"could not create device '{name}': {e}", file=sys.stderr)
        return 1
    print(f"Token for '{name}' (shown once, store it now):\n{token}")
    return 0


def token_list() -> int:
    for r in _db().execute("SELECT name, created_at, last_seen FROM devices ORDER BY id"):
        print(f"{r['name']}\tcreated {r['created_at']}\tlast seen {r['last_seen'] or 'never'}")
    return 0


def token_revoke(name: str) -> int:
    cur = _db().execute("DELETE FROM devices WHERE name = ?", (name,))
    print("revoked" if cur.rowcount else f"no device named '{name}'")
    return 0 if cur.rowcount else 1


def reembed(all_items: bool) -> int:
    """Embed items that have no vector yet (or all of them) with the configured model."""
    from vault.db.util import tx
    from vault.media.store import blob_path
    from vault.ml import registry
    from vault.ml.service import embed_file
    from vault.search import index

    settings = get_settings()
    registry.warm(settings)
    import time

    while registry.status()["state"] == "loading":
        time.sleep(0.5)
    emb = registry.get_embedder()
    if emb is None:
        print(f"embedding model unavailable: {registry.status()}", file=sys.stderr)
        return 1
    db = _db()
    table = index.ensure_table(db, emb.key, emb.dim)
    ids = (
        [r[0] for r in db.execute("SELECT id FROM items WHERE deleted_at IS NULL ORDER BY id")]
        if all_items else index.missing_ids(db, table)
    )
    done = 0
    for item_id in ids:
        row = db.execute(
            "SELECT sha256, kind, duration_ms FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        vec = embed_file(blob_path(settings, row["sha256"]), row["kind"], row["duration_ms"], emb)
        if vec is None:
            print(f"skipped item {item_id}", file=sys.stderr)
            continue
        with tx(db):
            index.upsert(db, table, item_id, vec)
        done += 1
        print(f"embedded {done}/{len(ids)}", end="\r", flush=True)
    print()
    return 0


def import_cmd(folder: str, recursive: bool, collection: str | None, tags: list[str]) -> int:
    from pathlib import Path

    from vault.maintenance import import_folder

    root = Path(folder)
    if not root.is_dir():
        print(f"not a folder: {folder}", file=sys.stderr)
        return 1
    settings = get_settings()
    report = import_folder(
        _db(), settings, root, recursive=recursive, collection=collection, tags=tags,
        progress=lambda n, total, p: print(f"\r[{n}/{total}] {p.name[:50]:<50}", end="", flush=True),
    )
    print(f"\nadded {report.added}, already present {report.duplicates}, skipped {len(report.skipped)}")
    for path, why in report.skipped[:20]:
        print(f"  skipped {path}: {why}", file=sys.stderr)
    return 0


def gc_cmd(days: int | None, dry_run: bool) -> int:
    from vault.maintenance import gc

    r = gc(_db(), get_settings(), purge_deleted_days=days, dry_run=dry_run)
    verb = "would free" if dry_run else "freed"
    print(f"purged items {r.purged_items}, orphan blobs {r.orphan_blobs}, orphan derived {r.orphan_derived}, "
          f"stale staging {r.stale_staging}, old jobs {r.old_jobs}; {verb} {r.bytes_freed / 1048576:.1f} MB")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="vault")
    sub = p.add_subparsers(dest="cmd", required=True)
    tok = sub.add_parser("token", help="manage device tokens").add_subparsers(dest="sub", required=True)
    tok.add_parser("create").add_argument("name")
    tok.add_parser("list")
    tok.add_parser("revoke").add_argument("name")
    re = sub.add_parser("reembed", help="compute embeddings for items that lack one")
    re.add_argument("--all", action="store_true", help="recompute every item")
    imp = sub.add_parser("import", help="add every image/video in a folder")
    imp.add_argument("folder")
    imp.add_argument("--no-recursive", dest="recursive", action="store_false")
    imp.add_argument("--collection", help="put imported items in this collection (created if missing)")
    imp.add_argument("--tag", action="append", default=[], dest="tags")
    gcp = sub.add_parser("gc", help="remove orphaned files and long-deleted items")
    gcp.add_argument("--purge-deleted-days", type=int, default=30, dest="days",
                     help="hard-delete items deleted this many days ago (default 30)")
    gcp.add_argument("--keep-deleted", action="store_const", const=None, dest="days")
    gcp.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.cmd == "import":
        raise SystemExit(import_cmd(args.folder, args.recursive, args.collection, args.tags))
    if args.cmd == "gc":
        raise SystemExit(gc_cmd(args.days, args.dry_run))
    if args.cmd == "reembed":
        raise SystemExit(reembed(args.all))
    if args.cmd == "token":
        code = {"create": lambda: token_create(args.name), "list": token_list,
                "revoke": lambda: token_revoke(args.name)}[args.sub]()
        raise SystemExit(code)


if __name__ == "__main__":
    main()
