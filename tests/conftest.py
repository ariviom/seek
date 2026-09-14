from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from harness import running

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChannel, FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import ChannelInfo


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(data_dir=tmp_path / "data")


@pytest.fixture
def transcripts() -> FakeTranscriptSource:
    return FakeTranscriptSource(
        channels=[
            FakeChannel(
                info=ChannelInfo(channel_id="UC-wright", name="Wood By Wright"),
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
    return FakeChatEngine()


@pytest.fixture
async def client(
    config: Config,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
    reranker: FakeReranker,
    engine: FakeChatEngine,
    tmp_path: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    # No web bundle: API tests don't need one.
    app = create_app(config, transcripts, embedder, reranker, engine, static_dir=tmp_path / "no-bundle")
    async with running(app) as c:
        yield c
