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


def main() -> None:
    p = argparse.ArgumentParser(prog="vault")
    sub = p.add_subparsers(dest="cmd", required=True)
    tok = sub.add_parser("token", help="manage device tokens").add_subparsers(dest="sub", required=True)
    tok.add_parser("create").add_argument("name")
    tok.add_parser("list")
    tok.add_parser("revoke").add_argument("name")
    args = p.parse_args()
    if args.cmd == "token":
        code = {"create": lambda: token_create(args.name), "list": token_list,
                "revoke": lambda: token_revoke(args.name)}[args.sub]()
        raise SystemExit(code)
