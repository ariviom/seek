from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from harness import Gate, add_mentor, fake_channel, fake_video, free_port, running, serving, start_sync, wait_for_syncs

from mentor import db, syncs
from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import ChatEngineStatus, VideoUnavailable
from mentor.status_command import format_list, format_status, list_all, status


def server_config(config: Config, url: str) -> Config:
    port = urlsplit(url).port
    assert port is not None
    return replace(config, port=port)


async def test_mentor_status_reports_the_running_servers_models_claude_cli_and_sync_queue(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-held", "Held", before_fetch=gate))
    server_engine = FakeChatEngine(engine_status=ChatEngineStatus("logged_out", "/usr/bin/claude", "Run claude auth login"))
    app = create_app(config, transcripts, FakeEmbedder(), FakeReranker(), server_engine, static_dir=tmp_path / "none")
    cli_engine = FakeChatEngine()

    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        wright = await add_mentor(client, "Paul Wright", "@woodbywright")
        rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")
        await start_sync(client, wright["channels"][0]["id"])
        await gate.wait_entered()
        await start_sync(client, rex["channels"][0]["id"])
        report = await status(server_config(config, url), cli_engine)
        gate.released.set()
        await wait_for_syncs(client)

    assert report.server_url == url
    assert report.models is not None
    assert {role: m.state for role, m in report.models.items()} == {"embedding": "ready", "reranker": "ready"}
    assert report.claude_cli == server_engine.engine_status
    assert [(s.channel_name, s.status) for s in report.syncs] == [("Wood By Wright", "running"), ("Rex Krueger", "queued")]
    assert format_status(report).splitlines() == [
        f"Server: running at {url}",
        "Models:",
        "  embedding: ready (fake-embedder)",
        f"  reranker: ready ({report.models['reranker'].name})",
        "Claude CLI: logged_out (/usr/bin/claude)",
        "  Run claude auth login",
        "Syncs: 1 running, 1 queued",
        "  running  Paul Wright / Wood By Wright",
        "  queued   Rex Krueger / Rex Krueger",
    ]


async def test_mentor_status_reads_the_store_and_checks_the_claude_cli_itself_when_no_server_answers(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    offline = replace(config, port=free_port())
    cli_engine = FakeChatEngine(engine_status=ChatEngineStatus("missing", None, "Install Claude Code"))
    nothing_yet = await status(offline, cli_engine)
    app = create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none")
    async with running(app) as client:
        wright = await add_mentor(client, "Paul Wright", "@woodbywright")
    await db.Database(config.database_path).run(lambda conn: syncs.enqueue(conn, wright["channels"][0]["id"]))

    report = await status(offline, cli_engine)

    assert (nothing_yet.server_url, nothing_yet.syncs) == (None, [])
    assert (report.server_url, report.models, report.claude_cli) == (None, None, cli_engine.engine_status)
    assert [(s.channel_name, s.status) for s in report.syncs] == [("Wood By Wright", "queued")]
    assert format_status(report).splitlines() == [
        "Server: not running (the models load when it starts)",
        "Claude CLI: missing",
        "  Install Claude Code",
        "Syncs: 0 running, 1 queued",
        "  queued   Paul Wright / Wood By Wright",
    ]


def seed_videos(transcripts: FakeTranscriptSource) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-ok", "Sharpening chisels"),
        fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only video", permanent=True)),
        fake_video("v-tip", "Quick tip", listed_duration=60, duration=60),
    ]


async def test_mentor_list_shows_mentors_and_channel_counts_from_the_server_or_the_store(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    seed_videos(transcripts)
    app = create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none")

    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        wright = await add_mentor(client, "Paul Wright", "@woodbywright")
        await client.post(f"/api/mentors/{wright['id']}/channels", json={"channel": "@wrightvlogs"})
        await start_sync(client, wright["channels"][0]["id"])
        [finished] = await wait_for_syncs(client)
        vlogs = (await client.get("/api/mentors")).json()[0]["channels"][1]
        await client.patch(f"/api/channels/{vlogs['id']}", json={"indexed": False})
        served = await list_all(server_config(config, url))
    stored = await list_all(replace(config, port=free_port()))

    assert served.server_url == url
    assert stored.server_url is None
    assert served.mentors == stored.mentors
    assert format_list(stored).splitlines() == [
        "Paul Wright",
        f"  Wood By Wright (UC-wright): 1 indexed, 1 failed, 1 excluded; last synced {finished['finished_at']}",
        "  Wright Vlogs (UC-wright-vlog, not indexed): 0 indexed, 0 failed, 0 excluded; never synced",
    ]


async def test_mentor_list_with_nothing_added_says_so(config: Config) -> None:
    report = await list_all(replace(config, port=free_port()))

    assert format_list(report) == "No Mentors yet."
    assert not config.database_path.exists()
