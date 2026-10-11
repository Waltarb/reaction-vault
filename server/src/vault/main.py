from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel

from vault import __version__
from vault.api import ingest, items, media
from vault.api.deps import COOKIE, get_db, hash_token, require_auth
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
    yield


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
    def session(body: SessionBody, response: Response, db=Depends(get_db)):
        """Trade a device token for an HttpOnly cookie so <img> and <video> requests are authorised."""
        if not db.execute("SELECT 1 FROM devices WHERE token_hash = ?", (hash_token(body.token),)).fetchone():
            raise HTTPException(401, "invalid token")
        response.set_cookie(COOKIE, body.token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 365)

    protected = APIRouter(dependencies=[Depends(require_auth)])
    protected.include_router(ingest.router)
    protected.include_router(items.router)
    protected.include_router(media.router)
    app.include_router(protected)

    return app


app = create_app()
