import hashlib
import secrets
import sqlite3
from collections.abc import Iterator

from fastapi import Cookie, Depends, Header, HTTPException

from vault.config import Settings, get_settings
from vault.db.connection import connect

COOKIE = "vault_token"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def get_db(settings: Settings = Depends(get_settings)) -> Iterator[sqlite3.Connection]:
    """One connection per request: sqlite3 connections are not safe to share across worker threads."""
    db = connect(settings.db_path)
    try:
        yield db
    finally:
        db.close()


def require_auth(
    authorization: str | None = Header(default=None),
    vault_token: str | None = Cookie(default=None),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.auth_disabled:
        return
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or vault_token
    if token:
        row = db.execute("SELECT id FROM devices WHERE token_hash = ?", (hash_token(token),)).fetchone()
        if row:
            db.execute(
                "UPDATE devices SET last_seen = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (row["id"],),
            )
            return
    raise HTTPException(status_code=401, detail="invalid or missing token")
