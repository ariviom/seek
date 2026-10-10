from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from harness import WRIGHT_AVATAR, running

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChannel, FakeChatEngine, FakeEmbedder, FakeReranker, FakeSecrets, FakeTranscriptSource
from seek.ports import ChannelInfo, ChatEngineStatus


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(data_dir=tmp_path / "data")


@pytest.fixture
def transcripts() -> FakeTranscriptSource:
    return FakeTranscriptSource(
        channels=[
            FakeChannel(
                info=ChannelInfo(channel_id="UC-wright", name="Wood By Wright", avatar_url=WRIGHT_AVATAR),
                handles=["@woodbywright", "https://www.youtube.com/@woodbywright"],
            ),
            FakeChannel(
                info=ChannelInfo(channel_id="UC-wright-vlog", name="Wright Vlogs"),
                handles=["@wrightvlogs"],
            ),
            FakeChannel(
                info=ChannelInfo(channel_id="UC-rex", name="Rex Krueger"),
                handles=["@rexkrueger"],
            ),
        ]
    )


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def reranker() -> FakeReranker:
    return FakeReranker()


@pytest.fixture
def engine() -> FakeChatEngine:
    """The Claude CLI engine, which answers by default: the fake API engine starts without a key."""
    return FakeChatEngine("cli")


@pytest.fixture
def api_engine() -> FakeChatEngine:
    return FakeChatEngine("api", engine_status=ChatEngineStatus("api", "no_key", None, "Add an Anthropic API key"))


@pytest.fixture
def secrets() -> FakeSecrets:
    return FakeSecrets()


@pytest.fixture
async def client(
    config: Config,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    api_engine: FakeChatEngine,
    secrets: FakeSecrets,
    tmp_path: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    # No web bundle: API tests don't need one.
    app = create_app(
        config,
        transcripts,
        embedder,
        reranker,
        engine,
        static_dir=tmp_path / "no-bundle",
        secrets=secrets,
        api_engine=api_engine,
    )
    async with running(app) as c:
        yield c
