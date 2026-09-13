from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import fake_ports


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(data_dir=tmp_path / "data")


@pytest.fixture
async def client(config: Config, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(config, fake_ports(), static_dir=tmp_path / "static")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7337") as c:
        yield c
