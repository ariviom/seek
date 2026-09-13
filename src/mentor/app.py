import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from mentor import db
from mentor.config import Config
from mentor.mentors import Conflict, NotFound
from mentor.mentors_api import mentors_router
from mentor.ports import ChannelNotFound, SourceUnavailable, TranscriptSource

PACKAGE_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    config: Config, transcripts: TranscriptSource, static_dir: Path = PACKAGE_STATIC_DIR
) -> FastAPI:
    database = db.Database(config.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fail at startup, not on first request, if the knowledge base can't be opened.
        app.state.database = await asyncio.to_thread(db.initialize, config.database_path)
        yield

    app = FastAPI(title="mentor", lifespan=lifespan)

    @app.exception_handler(ChannelNotFound)
    async def channel_not_found(request: Request, exc: ChannelNotFound) -> JSONResponse:
        return JSONResponse({"detail": f"No YouTube channel found for {exc}"}, status_code=422)

    @app.exception_handler(NotFound)
    async def not_found(request: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(SourceUnavailable)
    async def source_unavailable(request: Request, exc: SourceUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", "database": app.state.database}

    app.include_router(mentors_router(database, transcripts), prefix="/api")

    # Mounted last: a catch-all at "/" would shadow routes registered after it.
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
