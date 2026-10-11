from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vault import __version__
from vault.api import discover, ingest, items, media, search, sync
from vault.jobs import tasks
from vault.jobs.queue import Worker
from vault.ml import registry
from vault.api.deps import COOKIE, client_key, failures, get_db, hash_token, require_auth
from vault.config import get_settings
from vault.db.connection import connect
from vault.db.migrate import migrate
from vault.db.util import current_rev


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    db = connect(settings.db_path)
    migrate(db)
    db.close()
    registry.warm(settings)
    worker = None
    if settings.worker_enabled:
        worker = Worker(lambda: connect(settings.db_path), tasks.HANDLERS, on_idle=tasks.backfill_embeddings)
        worker.start()
    try:
        yield
    finally:
        if worker:
            worker.stop()


class SessionBody(BaseModel):
    token: str


def create_app() -> FastAPI:
    app = FastAPI(title="Reaction Vault", version=__version__, lifespan=lifespan)

    @app.get("/api/health")
    def health(db=Depends(get_db)) -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "schema": db.execute("PRAGMA user_version").fetchone()[0],
            "rev": current_rev(db),
            "items": db.execute("SELECT COUNT(*) FROM items WHERE deleted_at IS NULL").fetchone()[0],
        }

    @app.post("/api/session", status_code=204)
    def session(body: SessionBody, request: Request, response: Response, db=Depends(get_db)):
        """Trade a device token for an HttpOnly cookie so <img> and <video> requests are authorised."""
        key = client_key(request)
        if failures.blocked(key):
            raise HTTPException(429, "too many failed attempts, try again in a minute")
        if not db.execute("SELECT 1 FROM devices WHERE token_hash = ?", (hash_token(body.token),)).fetchone():
            failures.fail(key)
            raise HTTPException(401, "invalid token")
        response.set_cookie(
            COOKIE, body.token, httponly=True, samesite="strict",
            secure=request.url.scheme == "https",  # behind the TLS proxy, --proxy-headers makes this https
            max_age=60 * 60 * 24 * 365,
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if not request.url.path.startswith("/media/"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
            )
        return response

    protected = APIRouter(dependencies=[Depends(require_auth)])
    protected.include_router(ingest.router)
    protected.include_router(items.router)
    protected.include_router(search.router)
    protected.include_router(sync.router)
    protected.include_router(discover.router)
    protected.include_router(media.router)
    app.include_router(protected)

    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app


app = create_app()
