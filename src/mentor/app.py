import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from mentor import db
from mentor.config import Config
from mentor.errors import Conflict, NotFound
from mentor.groups_api import groups_router
from mentor.mentors_api import mentors_router
from mentor.ports import ChannelNotFound, SourceUnavailable, TranscriptSource

PACKAGE_STATIC_DIR = Path(__file__).parent / "static"

# Exceptions whose messages are written for the user, and the status each maps to.
ERROR_STATUS: dict[type[Exception], int] = {
    ChannelNotFound: 422,
    NotFound: 404,
    Conflict: 409,
    SourceUnavailable: 503,
}


async def _error_response(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=ERROR_STATUS[type(exc)])


def create_app(
    config: Config, transcripts: TranscriptSource, static_dir: Path = PACKAGE_STATIC_DIR
) -> FastAPI:
    database = db.Database(config.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fail at startup, not on first request, if the knowledge base can't be opened.
        app.state.database_info = await asyncio.to_thread(db.initialize, config.database_path)
        yield

    app = FastAPI(title="mentor", lifespan=lifespan)
    for exception in ERROR_STATUS:
        app.add_exception_handler(exception, _error_response)

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", "database": app.state.database_info}

    app.include_router(mentors_router(database, transcripts), prefix="/api")
    app.include_router(groups_router(database), prefix="/api")

    # Mounted last: a catch-all at "/" would shadow routes registered after it.
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
