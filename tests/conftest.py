from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from harness import running

from mentor.app import create_app
from mentor.config import Config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(data_dir=tmp_path / "data")


@pytest.fixture
async def client(config: Config, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    # No web bundle: API tests don't need one.
    async with running(create_app(config, static_dir=tmp_path / "no-bundle")) as c:
        yield c
