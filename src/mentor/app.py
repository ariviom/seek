import asyncio
import contextlib
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
from mentor.ports import ChannelNotFound, Embedder, SourceUnavailable, TranscriptSource
from mentor.sync_worker import SyncWorker
from mentor.syncs_api import syncs_router

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
    config: Config,
    transcripts: TranscriptSource,
    embedder: Embedder,
    static_dir: Path = PACKAGE_STATIC_DIR,
    sync_poll_seconds: float = 5.0,
) -> FastAPI:
    database = db.Database(config.database_path)
    worker = SyncWorker(database, transcripts, embedder, config.min_duration_seconds, sync_poll_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fail at startup, not on first request, if the knowledge base can't be opened.
        app.state.database_info = await asyncio.to_thread(
            db.initialize, config.database_path, embedder.model_name, embedder.dimension
        )
        worker_task = asyncio.create_task(worker.run())
        try:
            yield
        finally:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task

    app = FastAPI(title="mentor", lifespan=lifespan)
    for exception in ERROR_STATUS:
        app.add_exception_handler(exception, _error_response)

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", "database": app.state.database_info}

    app.include_router(mentors_router(database, transcripts), prefix="/api")
    app.include_router(groups_router(database), prefix="/api")
    app.include_router(syncs_router(database, worker.wake), prefix="/api")

    # Mounted last: a catch-all at "/" would shadow routes registered after it.
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
