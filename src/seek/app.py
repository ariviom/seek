import asyncio
import contextlib
import html
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Route

from seek import access, db
from seek.api_chat import ApiEngine
from seek.channels_api import channels_router
from seek.chat import Chat
from seek.chat_api import chat_router
from seek.checks import run_checks, utc_now
from seek.config import Config
from seek.credentials import Credentials
from seek.credentials_api import credentials_router
from seek.errors import Conflict, NotFound
from seek.events import Events
from seek.events_api import events_router
from seek.groups_api import groups_router
from seek.mcp_server import create_mcp_server
from seek.playlists_api import playlists_router
from seek.proxy import LOOPBACK_HOSTS, ProxyMiddleware
from seek.ports import (
    ChannelNotFound,
    ChatEngine,
    Embedder,
    Model,
    ModelStatus,
    ModelUnavailable,
    PlaylistNotFound,
    Reranker,
    Secrets,
    SecretsUnavailable,
    SourceUnavailable,
    TranscriptSource,
)
from seek.ranking import Recency
from seek.search import PreferRecent, Search
from seek.search_api import search_router
from seek.secrets import KeyringSecrets
from seek.settings_api import settings_router
from seek.storyboards_api import storyboards_router
from seek.sync_worker import SyncWorker
from seek.syncs_api import syncs_router

PACKAGE_STATIC_DIR = Path(__file__).parent / "static"

# Exceptions whose messages are written for the user, and the status each maps to.
ERROR_STATUS: dict[type[Exception], int] = {
    SecretsUnavailable: 503,
    ChannelNotFound: 422,
    PlaylistNotFound: 422,
    NotFound: 404,
    Conflict: 409,
    SourceUnavailable: 503,
    ModelUnavailable: 503,
}


def _statuses(models: Mapping[str, Model]) -> dict[str, ModelStatus]:
    return {role: model.status() for role, model in models.items()}


async def _load_models(
    models: Mapping[str, Model], events: Events, on_state_change: Callable[[], None], progress_seconds: float
) -> None:
    """Loads models in order and reports progress and runtime failures until shutdown."""
    loop = asyncio.get_running_loop()
    loaded = asyncio.Event()

    def load_all() -> None:
        try:
            for model in models.values():
                model.load()
        finally:
            # The loop is closed if the server stopped first.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(loaded.set)

    # A daemon thread, so stopping the server doesn't wait for a download to finish (a model already moving onto the
    # GPU finishes first, since the GPU thread is joined at exit).
    threading.Thread(target=load_all, name="seek-models", daemon=True).start()
    published: dict[str, ModelStatus] = {}
    while True:
        # Once startup completes, keep observing one-time device fallbacks and runtime failures.
        finished = loaded.is_set()
        statuses = _statuses(models)
        if statuses != published:
            events.models(statuses)
            if [s.state for s in statuses.values()] != [s.state for s in published.values()]:
                on_state_change()
            published = statuses
        if finished:
            await asyncio.sleep(progress_seconds)
        else:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(loaded.wait(), progress_seconds)


async def _serve_mcp(mcp: MCPServer, started: asyncio.Future[None]) -> None:
    """Runs the MCP session manager until cancelled, resolving `started` once it runs or failing it.

    In a task of its own because its cancel scope must exit in the task that entered it, and a lifespan can be
    entered and exited in different tasks (pytest fixtures do).
    """
    try:
        async with mcp.session_manager.run():
            started.set_result(None)
            await asyncio.Future[None]()
    except Exception as e:
        # Startup waits on `started`, so a failure before it runs must fail startup rather than hang it.
        if not started.done():
            started.set_exception(e)
        raise


async def _error_response(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=ERROR_STATUS[type(exc)])


def create_app(
    config: Config,
    transcripts: TranscriptSource,
    embedder: Embedder,
    reranker: Reranker,
    cli_engine: ChatEngine,
    static_dir: Path = PACKAGE_STATIC_DIR,
    sync_poll_seconds: float = 5.0,
    events_keepalive_seconds: float = 15.0,
    model_progress_seconds: float = 0.5,
    sql_time_limit_seconds: float = 5.0,
    fetch_access_keys: access.FetchKeys = access.fetch_url,
    access_keys_refetch_seconds: float = 60.0,
    secrets: Secrets | None = None,
    api_engine: ChatEngine | None = None,
    check_seconds: float = 300.0,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    database = db.Database(config.database_path)
    events = Events()
    credentials = Credentials(secrets if secrets is not None else KeyringSecrets(config.data_dir), events)
    recency: dict[PreferRecent, Recency | None] = {
        "off": None,
        "gentle": Recency(config.gentle_recency_half_life_days, config.gentle_recency_max_penalty_percent / 100),
        "strong": Recency(config.strong_recency_half_life_days, config.strong_recency_max_penalty_percent / 100),
    }
    search = Search(database, embedder, reranker, config.reranker_temperature, recency)
    worker = SyncWorker(
        database,
        transcripts,
        embedder,
        config.min_duration_seconds,
        sync_poll_seconds,
        events,
        cooldown_seconds=config.youtube_backoff_seconds,
    )
    models: dict[str, Model] = {"embedding": embedder, "reranker": reranker}
    chat = Chat(database, search, {"api": api_engine or ApiEngine(credentials), "cli": cli_engine})
    mcp = create_mcp_server(database, search, sql_time_limit_seconds)
    mcp_hosts = [*LOOPBACK_HOSTS, *config.allowed_hosts]
    # Stateless JSON responses: the tools never call back to the client, and plain responses pass through proxies
    # that buffer event streams.
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=mcp_hosts,
            allowed_origins=[f"{scheme}://{host}" for host in mcp_hosts for scheme in ("http", "https")],
        ),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fail at startup, not on first request, if the knowledge base can't be opened.
        app.state.database_info = await asyncio.to_thread(
            db.initialize, config.database_path, embedder.model_name, embedder.dimension
        )
        # Syncs wait for the embedding model, so the worker is woken as the models' statuses change.
        tasks = [
            asyncio.create_task(_load_models(models, events, worker.wake, model_progress_seconds)),
            asyncio.create_task(worker.run()),
            asyncio.create_task(run_checks(database, events, worker.wake, check_seconds, clock)),
        ]
        mcp_started = asyncio.get_running_loop().create_future()
        tasks.append(asyncio.create_task(_serve_mcp(mcp, mcp_started)))
        try:
            await mcp_started
            yield
        finally:
            await chat.close()
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="Seek", lifespan=lifespan)
    app.state.mcp = mcp
    app.state.credentials = credentials
    for exception in ERROR_STATUS:
        app.add_exception_handler(exception, _error_response)

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        # Both engines, so the settings screen can offer a choice this machine can honour, and the active
        # one, so the composer knows who would answer. Neither status calls a provider.
        active, engines = await chat.active()
        return {
            "status": "ok",
            "database": app.state.database_info,
            "models": _statuses(models),
            "chat": {"active": active, "engines": engines},
        }

    app.include_router(channels_router(database, transcripts, events), prefix="/api")
    app.include_router(playlists_router(database, transcripts), prefix="/api")
    app.include_router(groups_router(database), prefix="/api")
    app.include_router(settings_router(database, events), prefix="/api")
    app.include_router(credentials_router(credentials), prefix="/api")
    app.include_router(syncs_router(database, events, worker.wake), prefix="/api")
    app.include_router(search_router(search, database), prefix="/api")
    app.include_router(storyboards_router(database), prefix="/api")
    app.include_router(chat_router(database, chat, events_keepalive_seconds), prefix="/api")
    app.include_router(events_router(events, events_keepalive_seconds), prefix="/api")
    # The MCP app routes /mcp itself; its session manager runs in the lifespan above.
    app.router.routes.append(Route("/mcp", mcp_app))

    index = static_dir / "index.html"
    if index.is_file():

        @app.get("/", include_in_schema=False)
        async def web_ui(request: Request) -> HTMLResponse:
            # The bundle's URLs are relative; a <base> resolves them under a proxy prefix even when the page's URL
            # lacks the trailing slash.
            base = f'<base href="{html.escape(request.scope.get("root_path", ""))}/">'
            page = await asyncio.to_thread(index.read_text)
            return HTMLResponse(page.replace("<head>", f"<head>\n    {base}", 1))

    # Mounted last: a catch-all at "/" would shadow routes registered after it.
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    if config.cf_access_team_domain is not None and config.cf_access_aud is not None:
        verifier = access.AccessVerifier(
            config.cf_access_team_domain, config.cf_access_aud, fetch_access_keys, access_keys_refetch_seconds
        )
        app.add_middleware(access.AccessMiddleware, verifier=verifier)
    # Added last, so it runs first: a request through a host that isn't seek's is refused before anything else.
    app.add_middleware(ProxyMiddleware, allowed_hosts=config.allowed_hosts)
    return app
