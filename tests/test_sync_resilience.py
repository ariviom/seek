import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
import pytest
from harness import (
    Gate,
    add_channel,
    fake_channel,
    fake_video,
    fetched,
    list_videos,
    running,
    start_sync,
    wait_for_syncs,
)

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import GpuOutOfMemory, ModelUnavailable, VideoUnavailable


@dataclass
class FailsOn(FakeEmbedder):
    """Raises for any batch containing `word` while `error` is set."""

    word: str = ""
    error: Exception | None = None

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        if self.error is not None and any(self.word in t for t in texts):
            raise self.error
        return super().embed_passages(texts)


def embeds_of(embedder: FakeEmbedder, title: str) -> int:
    return sum(title in passage for passage in embedder.passages)


@pytest.mark.parametrize("interrupted_by", ["transcript source", "embedder"])
async def test_an_interrupted_sync_resumes_only_the_unfinished_videos_when_rerun(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, interrupted_by: str
) -> None:
    embedder = FailsOn(word="Second")

    def lose_network() -> None:
        transcripts.unavailable = "Network unreachable"

    second = fake_video("v-second", "Second")
    fake_channel(transcripts, "UC-wright").videos += [fake_video("v-first", "First"), second, fake_video("v-third", "Third")]
    if interrupted_by == "transcript source":
        second.before_fetch = lose_network
    else:
        embedder.error = ModelUnavailable("Network unreachable")

    async with running(create_app(config, transcripts, embedder, FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        channel_id = channel["id"]
        await start_sync(client, channel_id)
        [interrupted] = await wait_for_syncs(client)
        stages_after_interruption = {t: v["stage"] for t, v in (await list_videos(client, channel_id)).items()}
        second.before_fetch = None
        transcripts.unavailable = None
        embedder.error = None
        await start_sync(client, channel_id)
        resumed, _ = await wait_for_syncs(client)
        stages_after_resume = {t: v["stage"] for t, v in (await list_videos(client, channel_id)).items()}

    assert (interrupted["status"], interrupted["error"]) == ("failed", "Network unreachable")
    assert stages_after_interruption == {
        "First": "done",
        "Second": "discovered" if interrupted_by == "transcript source" else "segmented",
        "Third": "discovered",
    }
    assert resumed["status"] == "done"
    assert stages_after_resume == {"First": "done", "Second": "done", "Third": "done"}
    # The fake records a fetch before raising, so an interrupted fetch counts once per attempt.
    assert fetched(transcripts).count("v-first") == 1
    assert fetched(transcripts).count("v-second") == (2 if interrupted_by == "transcript source" else 1)
    assert fetched(transcripts).count("v-third") == 1
    assert [embeds_of(embedder, title) for title in ("First", "Second", "Third")] == [1, 1, 1]


async def test_a_video_that_does_not_fit_on_the_gpu_fails_alone_and_retry_failed_embeds_it_without_refetching(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    embedder = FailsOn(word="Second", error=GpuOutOfMemory("The GPU ran out of memory running the embedding model"))
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-first", "First"),
        fake_video("v-second", "Second"),
        fake_video("v-third", "Third"),
    ]

    async with running(create_app(config, transcripts, embedder, FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        channel_id = channel["id"]
        await start_sync(client, channel_id)
        [crowded] = await wait_for_syncs(client)
        after = await list_videos(client, channel_id)
        embedder.error = None
        response = await client.post(f"/api/channels/{channel_id}/retry-failed")
        assert response.status_code == 202, response.text
        retried, _ = await wait_for_syncs(client)
        after_retry = await list_videos(client, channel_id)

    # The other Videos were fetched and embedded; only the one that didn't fit waits, transcript kept.
    assert crowded["status"] == "done"
    assert {t: (v["stage"], v["failure_stage"]) for t, v in after.items()} == {
        "First": ("done", None),
        "Second": ("failed", "embedded"),
        "Third": ("done", None),
    }
    assert after["Second"]["reason"] == "The GPU ran out of memory running the embedding model"
    assert retried["status"] == "done"
    assert {t: v["stage"] for t, v in after_retry.items()} == {"First": "done", "Second": "done", "Third": "done"}
    assert fetched(transcripts).count("v-second") == 1
    assert embeds_of(embedder, "Second") == 1


async def test_a_normal_sync_skips_permanent_failures_and_retry_failed_recovers_every_failure(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    embedder = FailsOn(word="Garbled", error=ValueError("token sequence too long"))
    members = fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only video", permanent=True))
    upcoming = fake_video("v-live", "Live Q&A", failure=VideoUnavailable("Premieres in 3 days", permanent=False))
    fake_channel(transcripts, "UC-wright").videos += [
        members,
        upcoming,
        fake_video("v-garbled", "Garbled"),
        fake_video("v-ok", "Fine"),
    ]

    async with running(create_app(config, transcripts, embedder, FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        channel_id = channel["id"]
        await start_sync(client, channel_id)
        await wait_for_syncs(client)
        first = await list_videos(client, channel_id)
        # Both fetches would now succeed, but a normal Sync leaves the permanent failure alone.
        members.failure = None
        upcoming.failure = None
        await start_sync(client, channel_id)
        normal, _ = await wait_for_syncs(client)
        after_normal = await list_videos(client, channel_id)
        fetched_by_normal = fetched(transcripts)
        embedder.error = None
        response = await client.post(f"/api/channels/{channel_id}/retry-failed")
        retried, *_ = await wait_for_syncs(client)
        after_retry = await list_videos(client, channel_id)
        unknown = await client.post("/api/channels/999/retry-failed")

    assert {t: (v["stage"], v["failure_stage"], v["permanent_failure"]) for t, v in first.items()} == {
        "Members stream": ("failed", "transcript_fetched", True),
        "Live Q&A": ("failed", "transcript_fetched", False),
        "Garbled": ("failed", "embedded", False),
        "Fine": ("done", None, None),
    }
    assert normal["status"] == "done"
    assert {t: v["stage"] for t, v in after_normal.items()} == {
        "Members stream": "failed",
        "Live Q&A": "done",
        "Garbled": "failed",
        "Fine": "done",
    }
    assert fetched_by_normal.count("v-members") == 1
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "queued"
    assert queued["stage_counts"]["failed"] == 0
    assert retried["id"] == queued["id"]
    assert retried["status"] == "done"
    assert {t: (v["stage"], v["reason"]) for t, v in after_retry.items()} == {
        "Members stream": ("done", None),
        "Live Q&A": ("done", None),
        "Garbled": ("done", None),
        "Fine": ("done", None),
    }
    # Retried from the stage it failed at: embedded again, never fetched again.
    assert [fetched(transcripts).count(v) for v in ("v-members", "v-live", "v-garbled", "v-ok")] == [2, 2, 1, 1]
    assert [embeds_of(embedder, title) for title in ("Members stream", "Garbled", "Fine")] == [1, 1, 1]
    assert unknown.status_code == 404


async def test_a_refused_caption_fetch_fails_its_video_alone_and_a_run_of_them_stops_the_sync_and_cools_down(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    refused = VideoUnavailable("YouTube is rate limiting requests", permanent=False, throttled=True)
    videos_tab = fake_channel(transcripts, "UC-wright").videos
    videos_tab += [
        fake_video("v-one", "One", failure=refused),
        fake_video("v-two", "Two"),
        fake_video("v-three", "Three", failure=refused),
        fake_video("v-four", "Four", failure=refused),
        fake_video("v-five", "Five", failure=refused),
        fake_video("v-six", "Six"),
    ]
    app = create_app(
        # The cooldown after a throttled Sync is youtube_backoff_seconds, doubling for each in a row.
        replace(config, youtube_backoff_seconds=1),
        transcripts,
        FakeEmbedder(),
        FakeReranker(),
        FakeChatEngine(),
        static_dir=tmp_path / "no-bundle",
        sync_poll_seconds=0.2,
    )
    async with running(app) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        channel_id = channel["id"]
        await start_sync(client, channel_id)
        stopped, *_ = await wait_for_syncs(client)
        after = await list_videos(client, channel_id)
        fetched_first = fetched(transcripts)
        for video in videos_tab:
            video.failure = None
        started = time.monotonic()
        queued = await start_sync(client, channel_id)
        await asyncio.sleep(0.5)
        during = (await client.get("/api/syncs")).json()[0]
        rerun, *_ = await wait_for_syncs(client)
        cooled = time.monotonic() - started
        recovered = await list_videos(client, channel_id)

    # One refusal fails one Video; the Sync goes on until three in a row show YouTube is blocking this machine.
    assert stopped["status"] == "failed"
    assert "3 Videos in a row were refused" in stopped["error"]
    assert {t: v["stage"] for t, v in after.items()} == {
        "One": "failed",
        "Two": "done",
        "Three": "failed",
        "Four": "failed",
        "Five": "failed",
        "Six": "discovered",
    }
    assert after["One"]["permanent_failure"] is False
    assert fetched_first == ["v-one", "v-two", "v-three", "v-four", "v-five"]
    assert (during["id"], during["status"]) == (queued["id"], "queued")
    assert rerun["status"] == "done" and cooled >= 1
    assert {t: v["stage"] for t, v in recovered.items()} == {t: "done" for t in after}


async def test_syncs_already_queued_wait_out_the_cooldown_after_a_throttled_sync(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    refused = VideoUnavailable("YouTube is rate limiting requests", permanent=False, throttled=True)
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video(f"v-{n}", f"Refused {n}", failure=refused) for n in range(3)
    ]
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-rex", "Rex"))
    app = create_app(
        replace(config, youtube_backoff_seconds=1),
        transcripts,
        FakeEmbedder(),
        FakeReranker(),
        FakeChatEngine(),
        static_dir=tmp_path / "no-bundle",
        sync_poll_seconds=0.2,
    )
    async with running(app) as client:
        await add_channel(client, "@woodbywright", "Wood By Wright")
        await add_channel(client, "@rexkrueger", "Rex Krueger")
        response = await client.post("/api/syncs")
        started = time.monotonic()
        while (await client.get("/api/syncs")).json()[-1]["status"] in ("queued", "running"):
            await asyncio.sleep(0.05)
        throttled_at = time.monotonic() - started
        queued_after = (await client.get("/api/syncs")).json()[0]["status"]
        rex, wright = await wait_for_syncs(client)
        waited = time.monotonic() - started

    assert response.status_code == 202
    assert wright["status"] == "failed" and "Videos in a row were refused" in wright["error"]
    assert queued_after == "queued" and throttled_at < 1
    assert rex["status"] == "done" and waited >= 1
    assert fetched(transcripts) == ["v-0", "v-1", "v-2", "v-rex"]


async def test_retry_failed_during_a_sync_also_retries_failures_that_sync_records_afterwards(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    gate = Gate()
    members_only = VideoUnavailable("Members-only video", permanent=True)
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-members", "Members stream", before_fetch=gate, failure=members_only)
    )
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    await start_sync(client, channel_id)
    await gate.wait_entered()
    response = await client.post(f"/api/channels/{channel_id}/retry-failed")
    gate.released.set()
    retried, running_during_retry = await wait_for_syncs(client)

    assert response.status_code == 202
    assert retried["id"] == response.json()["id"]
    assert (running_during_retry["status"], retried["status"]) == ("done", "done")
    assert fetched(transcripts) == ["v-members", "v-members"]


async def test_one_permanently_failed_video_can_be_retried(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    members = fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only video", permanent=True))
    fake_channel(transcripts, "UC-wright").videos.append(members)

    app = create_app(
        config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle"
    )
    async with running(app) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        channel_id = channel["id"]
        await start_sync(client, channel_id)
        await wait_for_syncs(client)
        failed = (await list_videos(client, channel_id))["Members stream"]
        members.failure = None
        response = await client.post(f"/api/videos/{failed['id']}/retry")
        retried, *_ = await wait_for_syncs(client)
        after = (await list_videos(client, channel_id))["Members stream"]
        unknown = await client.post("/api/videos/999/retry")

    assert (failed["stage"], failed["permanent_failure"]) == ("failed", True)
    assert response.status_code == 202
    assert (response.json()["channel_id"], response.json()["status"]) == (channel_id, "queued")
    assert (retried["id"], retried["status"]) == (response.json()["id"], "done")
    assert (after["stage"], after["failure_stage"], after["reason"]) == ("done", None, None)
    assert fetched(transcripts).count("v-members") == 2
    assert unknown.status_code == 404


async def test_a_sync_resumed_after_a_restart_keeps_its_completed_videos_and_measures_a_fresh_interval(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    held_before = Gate()
    held_after = Gate()
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-one", "One"),
        fake_video("v-two", "Two"),
        fake_video("v-three", "Three", before_fetch=held_before),
        fake_video("v-four", "Four", before_fetch=held_after),
    ]

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        await held_before.wait_entered()
        [interrupted] = (await client.get("/api/syncs")).json()
    held_before.released.set()

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        # The Sync is running again and has just finished the Video the stopped process was holding.
        await held_after.wait_entered()
        [resumed] = (await client.get("/api/syncs")).json()
        held_after.released.set()
        [finished] = await wait_for_syncs(client)
        videos = await list_videos(client, channel["id"])

    assert (interrupted["status"], interrupted["completed_videos"], interrupted["counted_from"]) == ("running", 2, 0)
    # The two Videos finished before the restart are still counted, and the interval the rate is measured over
    # starts where this run does: one Video in, which is too few to claim a rate from.
    assert (resumed["status"], resumed["completed_videos"], resumed["counted_from"]) == ("running", 3, 2)
    # Same ISO 8601 UTC format throughout, so the strings order as the times do.
    assert resumed["started_at"] >= interrupted["started_at"]
    assert (finished["status"], finished["completed_videos"], finished["failed_videos"]) == ("done", 4, 0)
    assert [v["stage"] for v in videos.values()] == ["done"] * 4


async def test_a_failed_video_is_completed_work_that_leaves_nothing_to_search_and_retrying_it_counts_only_it(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    members = fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only video", permanent=True))
    fake_channel(transcripts, "UC-wright").videos += [fake_video("v-one", "One"), members, fake_video("v-two", "Two")]

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        [first] = await wait_for_syncs(client)
        members.failure = None
        await client.post(f"/api/channels/{channel['id']}/retry-failed")
        retried, _ = await wait_for_syncs(client)

    # All three Videos were worked through; only two of them can answer anything.
    assert (first["completed_videos"], first["failed_videos"]) == (3, 1)
    assert first["stage_counts"]["done"] == 2
    # The retry's work is the one Video it was queued for, not the Channel's three.
    assert (retried["completed_videos"], retried["failed_videos"]) == (1, 0)
    assert retried["stage_counts"] == first["stage_counts"] | {"done": 3, "failed": 0}
