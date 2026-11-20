import logging
from contextlib import asynccontextmanager
from pathlib import PurePosixPath

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException

from .catalog import router
from .config import ROOT, Settings
from .database import make_engine

logger = logging.getLogger(__name__)
PUBLIC_SUFFIXES = {
    ".html",
    ".css",
    ".js",
    ".svg",
    ".mp4",
    ".webm",
    ".jpg",
    ".jpeg",
    ".png",
    ".ico",
    ".woff",
    ".woff2",
}


class PublicFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if path not in {"", "."} and PurePosixPath(path).suffix.lower() not in PUBLIC_SUFFIXES:
            raise HTTPException(404)
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def create_app(settings: Settings | None = None, *, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = engine or make_engine(settings)
    migration_config = Config(str(ROOT / "alembic.ini"))
    expected_schema = ScriptDirectory.from_config(migration_config).get_current_head()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(title="OmniSport Digitale API", version="0.2.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessions = sessionmaker(engine, expire_on_commit=False)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        logger.warning("Database request failed (%s)", type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={"detail": "Service temporarily unavailable. Please try again."},
            headers={"Retry-After": "5"},
        )

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready():
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if revision != expected_schema:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return {"status": "ready"}

    app.include_router(router)
    app.mount("/", PublicFiles(directory=ROOT / "frontend" / "dist", html=True), name="website")
    return app
