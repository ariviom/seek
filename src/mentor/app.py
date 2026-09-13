import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mentor import db
from mentor.config import Config
from mentor.ports import Ports

PACKAGE_STATIC_DIR = Path(__file__).parent / "static"


def create_app(config: Config, ports: Ports | None, static_dir: Path = PACKAGE_STATIC_DIR) -> FastAPI:
    # ports is None until the real adapters exist (tickets 04, 08, 10, 12).
    app = FastAPI(title="mentor")

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        database = await asyncio.to_thread(db.describe, config.database_path)
        return {"status": "ok", "database": database}

    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
