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


def main() -> None:
    p = argparse.ArgumentParser(prog="vault")
    sub = p.add_subparsers(dest="cmd", required=True)
    tok = sub.add_parser("token", help="manage device tokens").add_subparsers(dest="sub", required=True)
    tok.add_parser("create").add_argument("name")
    tok.add_parser("list")
    tok.add_parser("revoke").add_argument("name")
    re = sub.add_parser("reembed", help="compute embeddings for items that lack one")
    re.add_argument("--all", action="store_true", help="recompute every item")
    args = p.parse_args()
    if args.cmd == "reembed":
        raise SystemExit(reembed(args.all))
    if args.cmd == "token":
        code = {"create": lambda: token_create(args.name), "list": token_list,
                "revoke": lambda: token_revoke(args.name)}[args.sub]()
        raise SystemExit(code)


if __name__ == "__main__":
    main()
