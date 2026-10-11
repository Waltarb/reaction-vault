from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from vault import __version__
from vault.config import get_settings
from vault.db.connection import connect
from vault.db.migrate import migrate


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    db = connect(settings.db_path)
    migrate(db)
    app.state.db = db
    try:
        yield
    finally:
        db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Reaction Vault", version=__version__, lifespan=lifespan)

    @app.get("/api/health")
    def health(request: Request) -> dict:
        db = request.app.state.db
        return {
            "status": "ok",
            "version": __version__,
            "schema": db.execute("PRAGMA user_version").fetchone()[0],
            "items": db.execute("SELECT COUNT(*) FROM items WHERE deleted_at IS NULL").fetchone()[0],
        }

    return app


app = create_app()
