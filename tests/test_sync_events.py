from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from harness import (
    Gate,
    Json,
    add_mentor,
    event_stream,
    fake_channel,
    fake_video,
    running,
    start_sync,
)

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import VideoUnavailable

NO_COUNTS = {
    "discovered": 0,
    "transcript_fetched": 0,
    "segmented": 0,
    "embedded": 0,
    "done": 0,
    "failed": 0,
    "excluded": 0,
}


def make_app(config: Config, transcripts: FakeTranscriptSource, tmp_path: Path) -> FastAPI:
    return create_app(
        config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle", events_keepalive_seconds=0.02
    )


def sync_status(status: str) -> Callable[[Json], bool]:
    return lambda event: event["type"] == "sync" and event["sync"]["status"] == status


def syncs_in(events: list[Json]) -> list[Json]:
    return [event["sync"] for event in events if event["type"] == "sync"]


def stages_of(events: list[Json], title: str) -> list[str]:
    return [e["video"]["stage"] for e in events if e["type"] == "video" and e["video"]["title"] == title]


async def test_sync_progress_and_video_stages_stream_live_while_the_sync_runs(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-first", "First"),
        fake_video("v-second", "Second", before_fetch=gate),
    ]
    app = make_app(config, transcripts, tmp_path)

    async with running(app) as client, event_stream(app) as stream:
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        channel_id = mentor["channels"][0]["id"]
        queued = await start_sync(client, channel_id)
        await gate.wait_entered()
        before_release = await stream.until(lambda e: e["type"] == "sync" and e["sync"]["stage_counts"]["done"] == 1)
        # The worker is now blocked in the fetch; the stream must keep flowing regardless.
        await stream.wait_for_comments(3)
        gate.released.set()
        after_release = await stream.until(sync_status("done"))
        [listed] = (await client.get("/api/syncs")).json()

    progress = syncs_in(before_release)
    assert [s["status"] for s in progress[:2]] == ["queued", "running"]
    assert all(s["id"] == queued["id"] for s in progress)
    assert {"type": "videos", "channel_id": channel_id} in before_release
    discovered = next(s for s in progress if s["new_videos"] == 2)
    assert discovered["stage_counts"] == NO_COUNTS | {"discovered": 2}
    assert progress[-1]["stage_counts"] == NO_COUNTS | {"discovered": 1, "done": 1}
    assert stages_of(before_release, "First") == ["transcript_fetched", "segmented", "embedded", "done"]
    assert all(e["channel_id"] == channel_id for e in before_release if e["type"] == "video")
    assert stages_of(after_release, "Second") == ["transcript_fetched", "segmented", "embedded", "done"]
    assert syncs_in(after_release)[-1] == listed
    assert listed["stage_counts"] == NO_COUNTS | {"done": 2}


async def test_failures_and_retry_failed_stream_over_events(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    live = fake_video("v-live", "Live Q&A", failure=VideoUnavailable("Premieres in 3 days", permanent=False))
    fake_channel(transcripts, "UC-wright").videos.append(live)
    app = make_app(config, transcripts, tmp_path)

    async with running(app) as client, event_stream(app) as stream:
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        channel_id = mentor["channels"][0]["id"]
        await start_sync(client, channel_id)
        first_sync = await stream.until(sync_status("done"))
        live.failure = None
        retry = await client.post(f"/api/channels/{channel_id}/retry-failed")
        retried = await stream.until(sync_status("done"))

    [failed] = [e["video"] for e in first_sync if e["type"] == "video"]
    assert (failed["stage"], failed["reason"], failed["permanent_failure"]) == ("failed", "Premieres in 3 days", False)
    assert syncs_in(first_sync)[-1]["stage_counts"] == NO_COUNTS | {"failed": 1}
    assert retry.status_code == 202
    assert retried[0] == {"type": "videos", "channel_id": channel_id}
    assert syncs_in(retried)[0] == retry.json()
    assert stages_of(retried, "Live Q&A")[-1] == "done"


async def test_the_event_stream_is_proxy_safe(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    app = make_app(config, transcripts, tmp_path)

    async with running(app), event_stream(app) as stream:
        await stream.wait_for_comments(2)

    assert stream.status == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["cache-control"] == "no-cache, no-transform"
    assert stream.headers["x-accel-buffering"] == "no"


async def test_renaming_or_removing_mentors_and_channels_asks_clients_to_reload_syncs(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    app = make_app(config, transcripts, tmp_path)
    reload = {"type": "syncs"}

    async with running(app) as client, event_stream(app) as stream:
        wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
        vlog = (await client.post(f"/api/mentors/{wright['id']}/channels", json={"channel": "@wrightvlogs"})).json()
        await client.patch(f"/api/mentors/{wright['id']}", json={"name": "Wright"})
        renamed = await stream.until(lambda e: e == reload)
        await client.delete(f"/api/channels/{vlog['id']}")
        detached = await stream.until(lambda e: e == reload)
        await client.delete(f"/api/mentors/{wright['id']}")
        deleted = await stream.until(lambda e: e == reload)

    assert [renamed, detached, deleted] == [[reload], [reload], [reload]]


async def test_a_running_sync_names_the_video_it_is_fetching(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-held", "Held fetch", before_fetch=gate))
    app = make_app(config, transcripts, tmp_path)

    async with running(app) as client, event_stream(app) as stream:
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        await start_sync(client, mentor["channels"][0]["id"])
        fetching = await stream.until(lambda e: e["type"] == "sync" and e["sync"]["fetching"] is not None)
        gate.released.set()
        finished = await stream.until(sync_status("done"))
        [listed] = (await client.get("/api/syncs")).json()

    assert syncs_in(fetching)[-1]["fetching"] == "Held fetch"
    assert syncs_in(finished)[-1]["fetching"] is None
    assert listed["fetching"] is None
