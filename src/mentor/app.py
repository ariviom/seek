import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mentor import db
from mentor.config import Config

PACKAGE_STATIC_DIR = Path(__file__).parent / "static"


def create_app(config: Config, static_dir: Path = PACKAGE_STATIC_DIR) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fail at startup, not on first request, if the knowledge base can't be opened.
        app.state.database = await asyncio.to_thread(db.describe, config.database_path)
        yield

    app = FastAPI(title="mentor", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", "database": app.state.database}

    # Mounted last: a catch-all at "/" would shadow routes registered after it.
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
