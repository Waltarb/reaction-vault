import hashlib
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterator

from fastapi import Cookie, Depends, Header, HTTPException, Request

from vault.config import Settings, get_settings
from vault.db.connection import connect

COOKIE = "vault_token"


class FailureLimiter:
    """Sliding-window cap on failed auth attempts per client address (in-memory, single process)."""

    def __init__(self, limit: int = 20, window: float = 60.0):
        self.limit, self.window = limit, window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key, time.monotonic())) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            hits = self._recent(key, now)
            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 10_000:  # bound memory under address spraying
                self._hits.clear()


failures = FailureLimiter()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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
    request: Request,
    authorization: str | None = Header(default=None),
    vault_token: str | None = Cookie(default=None),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.auth_disabled:
        return
    key = client_key(request)
    if failures.blocked(key):
        raise HTTPException(429, "too many failed attempts, try again in a minute")
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
    if token:  # a missing token is not a guess; only wrong tokens count
        failures.fail(key)
    raise HTTPException(status_code=401, detail="invalid or missing token")
