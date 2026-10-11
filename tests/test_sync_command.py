import asyncio
import threading
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from harness import (
    Gate,
    add_channel,
    fake_channel,
    fake_video,
    fetched,
    free_port,
    running,
    serving,
    start_sync,
    wait_for_syncs,
)

from seek import db, syncs
from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from seek.sync_command import SyncCommandError, sync_channels
from seek.videos import Source


def with_videos(transcripts: FakeTranscriptSource, gate: Gate | None = None) -> FakeTranscriptSource:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-wright", "Wright video", before_fetch=gate))
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-rex", "Rex video"))
    return transcripts


def fresh_source(transcripts: FakeTranscriptSource, gate: Gate | None = None) -> FakeTranscriptSource:
    """Another process's view of the same YouTube channels."""
    return with_videos(FakeTranscriptSource(channels=[replace(c, videos=[]) for c in transcripts.channels]), gate)


async def seed_channels(config: Config, transcripts: FakeTranscriptSource, tmp_path: Path) -> None:
    """Adds Wright and Rex through a server that then stops."""
    app = create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none")
    async with running(app) as client:
        await add_channel(client, "@woodbywright", "Wood By Wright")
        await add_channel(client, "@rexkrueger", "Rex Krueger")


async def test_seek_sync_hands_the_syncs_to_the_running_server(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    with_videos(transcripts)
    app = create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none")
    cli_source, cli_embedder = FakeTranscriptSource(), FakeEmbedder()

    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        await add_channel(client, "@woodbywright", "Wood By Wright")
        await add_channel(client, "@rexkrueger", "Rex Krueger")
        port = urlsplit(url).port
        assert port is not None
        report = await sync_channels(replace(config, port=port), None, cli_source, cli_embedder)
        finished = await wait_for_syncs(client)

    assert report.server_url == url
    assert [(s.source_name, s.status) for s in report.syncs] == [("Wood By Wright", "queued"), ("Rex Krueger", "queued")]
    assert [(s["id"], s["status"]) for s in finished] == [(s.id, "done") for s in reversed(report.syncs)]
    # The server's models did the work; this process loaded none and called nothing.
    assert cli_embedder.status().state == "waiting"
    assert cli_source.calls == []


async def test_seek_reindex_hands_reindex_syncs_to_the_running_server(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    with_videos(transcripts)
    embedder = FakeEmbedder()
    app = create_app(config, transcripts, embedder, FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none")

    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        rex = await add_channel(client, "@rexkrueger", "Rex Krueger")
        await start_sync(client, rex["id"])
        await wait_for_syncs(client)
        port = urlsplit(url).port
        assert port is not None
        report = await sync_channels(
            replace(config, port=port), None, FakeTranscriptSource(), FakeEmbedder(), reindex=True
        )
        finished = await wait_for_syncs(client)

    assert report.server_url == url
    assert [(s["status"], s["stage_counts"]["done"]) for s in finished] == [("done", 1), ("done", 1)]
    assert fetched(transcripts) == ["v-rex"]
    assert len(embedder.passages) == 2


async def test_seek_sync_hands_one_channel_to_the_running_server_by_its_youtube_channel_id(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    with_videos(transcripts)
    app = create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none")

    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        await add_channel(client, "@woodbywright", "Wood By Wright")
        await add_channel(client, "@rexkrueger", "Rex Krueger")
        port = urlsplit(url).port
        assert port is not None
        report = await sync_channels(replace(config, port=port), "UC-rex", FakeTranscriptSource(), FakeEmbedder())
        finished = await wait_for_syncs(client)

    assert report.server_url == url
    assert [(s.source_name, s.status) for s in report.syncs] == [("Rex Krueger", "queued")]
    assert [(s["source_name"], s["status"]) for s in finished] == [("Rex Krueger", "done")]
    assert fetched(transcripts) == ["v-rex"]


async def test_seek_sync_hands_one_channel_to_the_running_server_by_its_name(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    with_videos(transcripts)
    app = create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none")

    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        await add_channel(client, "@woodbywright", "Wood By Wright")
        await add_channel(client, "@rexkrueger", "Rex Krueger")
        port = urlsplit(url).port
        assert port is not None
        report = await sync_channels(replace(config, port=port), "Rex Krueger", FakeTranscriptSource(), FakeEmbedder())
        finished = await wait_for_syncs(client)

    assert report.server_url == url
    assert [(s.source_name, s.status) for s in report.syncs] == [("Rex Krueger", "queued")]
    assert [(s["source_name"], s["status"]) for s in finished] == [("Rex Krueger", "done")]
    assert fetched(transcripts) == ["v-rex"]


async def test_seek_sync_runs_a_channel_named_by_its_name_itself_when_no_server_answers(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    await seed_channels(config, transcripts, tmp_path)
    cli_source = fresh_source(transcripts)

    report = await sync_channels(replace(config, port=free_port()), "rex krueger", cli_source, FakeEmbedder())

    assert report.server_url is None
    assert [(s.source_name, s.status, s.new_videos) for s in report.syncs] == [("Rex Krueger", "done", 1)]
    assert fetched(cli_source) == ["v-rex"]


async def test_seek_sync_runs_a_channel_named_by_its_youtube_channel_id_itself_when_no_server_answers(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    await seed_channels(config, transcripts, tmp_path)
    cli_source = fresh_source(transcripts)

    report = await sync_channels(replace(config, port=free_port()), "UC-rex", cli_source, FakeEmbedder())

    assert report.server_url is None
    assert [(s.source_name, s.status, s.new_videos) for s in report.syncs] == [("Rex Krueger", "done", 1)]
    assert fetched(cli_source) == ["v-rex"]


async def test_an_unknown_channel_is_reported_rather_than_synced(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    await seed_channels(config, transcripts, tmp_path)

    with pytest.raises(SyncCommandError, match="No Channel named 'Paul Sellers'"):
        await sync_channels(replace(config, port=free_port()), "Paul Sellers", transcripts, FakeEmbedder())


async def test_seek_sync_and_a_server_starting_meanwhile_never_both_run_syncs(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    await seed_channels(config, transcripts, tmp_path)
    gate = Gate()
    cli_source = fresh_source(transcripts, gate)
    server_source = fresh_source(transcripts)
    cli_config = replace(config, port=free_port())

    command = asyncio.create_task(sync_channels(cli_config, None, cli_source, FakeEmbedder(), poll_seconds=0.02))
    await gate.wait_entered()
    app = create_app(
        config, server_source, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none",
        sync_poll_seconds=0.02,
    )
    async with running(app) as client:
        response = await client.post("/api/syncs")
        await asyncio.sleep(0.3)
        server_calls_while_cli_ran = list(server_source.calls)
        gate.released.set()
        report = await asyncio.wait_for(command, 5)
        finished = await wait_for_syncs(client)

    assert response.status_code == 202
    assert server_calls_while_cli_ran == []
    assert [(s.source_name, s.status) for s in report.syncs] == [("Wood By Wright", "done"), ("Rex Krueger", "done")]
    assert all(s["status"] == "done" for s in finished)
    assert sorted(fetched(cli_source) + fetched(server_source)) == ["v-rex", "v-wright"]


async def test_a_second_seek_sync_waits_for_its_own_channel_while_the_first_runs_the_queue(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    await seed_channels(config, transcripts, tmp_path)
    first_gate, later_gate = Gate(), Gate()
    first_source = fresh_source(transcripts, first_gate)
    second_source = fresh_source(transcripts)
    cli_config = replace(config, port=free_port())

    first = asyncio.create_task(sync_channels(cli_config, None, first_source, FakeEmbedder(), poll_seconds=0.02))
    await first_gate.wait_entered()
    # The second command loads its model once its Sync is queued.
    second_queued = threading.Event()
    second_embedder = FakeEmbedder(before_load=second_queued.set)
    second = asyncio.create_task(
        sync_channels(cli_config, "Rex Krueger", second_source, second_embedder, poll_seconds=0.02)
    )
    assert await asyncio.to_thread(second_queued.wait, 5)
    # Another Sync of Wright, queued behind Rex, finds a new Video that holds the first command.
    fake_channel(first_source, "UC-wright").videos.append(fake_video("v-wright-2", "Wright two", before_fetch=later_gate))
    await db.Database(config.database_path).run(lambda conn: syncs.enqueue(conn, Source("channel", 1)))
    first_gate.released.set()
    await later_gate.wait_entered()
    second_report = await asyncio.wait_for(second, 5)
    later_gate.released.set()
    first_report = await asyncio.wait_for(first, 5)

    assert second_report.server_url is None
    assert [(s.source_name, s.status) for s in second_report.syncs] == [("Rex Krueger", "done")]
    assert second_report.syncs[0].id == first_report.syncs[1].id
    assert second_source.calls == []
    assert fetched(first_source) == ["v-wright", "v-rex", "v-wright-2"]


async def test_seek_sync_asks_for_a_youtube_channel_id_when_two_channels_share_the_name(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    app = create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none")
    async with running(app) as client:
        await add_channel(client, "@woodbywright", "Wright")
        await add_channel(client, "@wrightvlogs", "Wright")

    with pytest.raises(SyncCommandError, match="More than one Channel is named 'wright'.*UC-wright, UC-wright-vlog"):
        await sync_channels(replace(config, port=free_port()), "wright", fresh_source(transcripts), FakeEmbedder())
