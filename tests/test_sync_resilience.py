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
    add_playlist,
    fake_channel,
    fake_video,
    fetched,
    list_videos,
    running,
    start_sync,
    wait_for_syncs,
)

from seek import db, syncs
from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakePlaylist, FakeReranker, FakeTranscriptSource
from seek.ports import GpuOutOfMemory, ModelUnavailable, VideoUnavailable


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
    assert "the Channel's remaining Videos wait" in stopped["error"]
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


@pytest.mark.parametrize("kind", ["channels", "playlists"])
async def test_a_sync_interrupted_with_a_newer_one_queued_behind_it_gives_way_to_that_one_after_a_restart(
    kind: str, config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    held = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One", before_fetch=held))
    transcripts.playlists["PL-one"] = FakePlaylist("One", [("UC-wright", "v-one")])

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        added = await (add_channel(client, "@woodbywright") if kind == "channels" else add_playlist(client, "PL-one"))
        interrupted = (await client.post(f"/api/{kind}/{added['id']}/syncs")).json()
        await held.wait_entered()
        newer = (await client.post(f"/api/{kind}/{added['id']}/syncs")).json()
    held.released.set()

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        after_restart = await wait_for_syncs(client)

    # Requeuing the interrupted Sync beside the newer one would break the rule of one queued Sync for each
    # Channel or Playlist, and no Sync could be claimed again.
    assert newer["id"] != interrupted["id"]
    assert [(s["id"], s["status"], s["error"]) for s in after_restart] == [
        (newer["id"], "done", None),
        (interrupted["id"], "failed", "Interrupted"),
    ]


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
    assert first["remaining_videos"] == retried["remaining_videos"] == 0
    assert retried["stage_counts"] == first["stage_counts"] | {"done": 3, "failed": 0}


async def test_a_retry_resumed_after_a_restart_does_not_count_the_videos_it_is_about_to_retry_again(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    held = Gate()
    members = fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only", permanent=True))
    age = fake_video("v-age", "Axe safety", failure=VideoUnavailable("Age-restricted", permanent=True))
    live = fake_video("v-live", "Live Q&A", failure=VideoUnavailable("Premieres in 3 days", permanent=True))
    fake_channel(transcripts, "UC-wright").videos += [members, age, live]

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        await wait_for_syncs(client)
        # A retry that hits the same failures again, stopped partway through by the process going down.
        live.before_fetch = held
        await client.post(f"/api/channels/{channel['id']}/retry-failed")
        await held.wait_entered()
        [retry, _] = (await client.get("/api/syncs")).json()
    held.released.set()

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        resumed, _ = await wait_for_syncs(client, timeout=10)
        videos = await list_videos(client, channel["id"])

    assert (retry["status"], retry["completed_videos"], retry["failed_videos"]) == ("running", 2, 2)
    assert retry["remaining_videos"] == 1
    # Resuming cleared those two failures to try them again, so they stopped being work this Sync had done.
    # Counting them as well as the three Videos still to come would have claimed five of a three-Video Channel.
    assert (resumed["status"], resumed["completed_videos"], resumed["failed_videos"]) == ("done", 3, 3)
    assert (resumed["counted_from"], resumed["remaining_videos"]) == (0, 0)
    assert [v["stage"] for v in videos.values()] == ["failed"] * 3


async def test_a_reindex_resumed_after_a_restart_counts_each_video_once_and_never_more_than_the_channel_has(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    held = Gate()
    channel_videos = fake_channel(transcripts, "UC-wright").videos
    channel_videos += [fake_video("v-one", "One"), fake_video("v-two", "Two"), fake_video("v-three", "Three")]

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        await wait_for_syncs(client)
        # A reindex that has re-cut the three indexed Videos and is fetching a new one when the process stops.
        channel_videos.append(fake_video("v-new", "New", before_fetch=held))
        await client.post(f"/api/channels/{channel['id']}/syncs", json={"reindex": True})
        await held.wait_entered()
        [interrupted, _] = (await client.get("/api/syncs")).json()
    held.released.set()

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        resumed, _ = await wait_for_syncs(client, timeout=10)
        videos = await list_videos(client, channel["id"])

    assert (interrupted["status"], interrupted["completed_videos"], interrupted["remaining_videos"]) == ("running", 3, 1)
    # Resuming stepped the three back again and re-cut them, so each was processed twice by this Sync. Counting
    # the events would have claimed seven Videos done of a four-Video Channel.
    assert (resumed["status"], resumed["completed_videos"], resumed["remaining_videos"]) == ("done", 4, 0)
    assert (resumed["failed_videos"], resumed["counted_from"]) == (0, 0)
    assert [v["stage"] for v in videos.values()] == ["done"] * 4


async def test_a_video_left_failed_by_an_earlier_sync_is_work_the_next_one_still_has_to_do(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    held = Gate()
    flaky = fake_video("v-flaky", "Flaky", failure=VideoUnavailable("Timed out", permanent=False))
    fake_channel(transcripts, "UC-wright").videos += [fake_video("v-one", "One"), flaky]

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        [first] = await wait_for_syncs(client)
        flaky.failure = None
        flaky.before_fetch = held
        await start_sync(client, channel["id"])
        await held.wait_entered()
        [running_sync, _] = (await client.get("/api/syncs")).json()
        held.released.set()
        finished, first_after = await wait_for_syncs(client)

    assert (first["completed_videos"], first["failed_videos"], first["remaining_videos"]) == (2, 1, 0)
    # The transient failure is retried by the next Sync, so it is that Sync's whole remaining work even while the
    # Video still shows as failed; the Video already done is no part of it.
    assert (running_sync["completed_videos"], running_sync["remaining_videos"]) == (0, 1)
    assert (finished["completed_videos"], finished["failed_videos"], finished["remaining_videos"]) == (1, 0, 0)
    # A finished Sync keeps its own counts after a later one takes its Video over.
    assert first_after == first


def test_marking_a_video_finished_again_does_not_count_it_again(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seek.db")
    db.migrate(conn)
    conn.executescript(
        """
        INSERT INTO channels (id, youtube_channel_id, name) VALUES (3, 'UC-wright', 'Wood By Wright');
        INSERT INTO videos (id, channel_id, youtube_video_id, title, pipeline_stage, discovered_at)
            VALUES (11, 3, 'v-one', 'One', 'done', '2025-01-01T00:00:00+00:00'),
                   (12, 3, 'v-two', 'Two', 'discovered', '2025-01-01T00:00:00+00:00');
        INSERT INTO syncs (id, channel_id, status, queued_at, stage_counts) VALUES (4, 3, 'running', '2025-01-01', '{}');
        """
    )

    once = syncs.update_progress(conn, 4, finished_video_id=11)
    twice = syncs.update_progress(conn, 4, finished_video_id=11)

    assert once is not None and twice is not None
    assert (once.completed_videos, once.remaining_videos) == (twice.completed_videos, twice.remaining_videos) == (1, 1)
    conn.close()


async def test_every_refused_video_of_a_throttled_sync_counts_as_failed_including_the_one_that_stopped_it(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    refused = VideoUnavailable("YouTube is rate limiting requests", permanent=False, throttled=True)
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video(f"v-{n}", f"Video {n}", failure=refused) for n in ("one", "two", "three")
    ]

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        [stopped] = await wait_for_syncs(client)

    assert stopped["status"] == "failed"
    assert (stopped["completed_videos"], stopped["failed_videos"], stopped["remaining_videos"]) == (3, 3, 0)
    assert stopped["stage_counts"]["failed"] == 3


async def test_a_failure_retried_while_a_sync_runs_is_left_to_the_retry_rather_than_to_the_running_sync(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    held = Gate()
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only", permanent=True)),
        fake_video("v-one", "One", before_fetch=held),
    ]

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        await held.wait_entered()
        await client.post(f"/api/channels/{channel['id']}/retry-failed")
        held.released.set()
        retry, first = await wait_for_syncs(client)

    # The running Sync had already been through the failed Video, so it finished without it rather than
    # finishing done with work it claimed to have left; the retry queued for it did it.
    assert (first["status"], first["completed_videos"], first["failed_videos"], first["remaining_videos"]) == (
        "done", 1, 0, 0
    )
    assert (retry["status"], retry["completed_videos"], retry["failed_videos"], retry["remaining_videos"]) == (
        "done", 1, 1, 0
    )


def test_a_video_leaving_the_completed_count_starts_the_rate_interval_again(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seek.db")
    db.migrate(conn)
    conn.executescript(
        """
        INSERT INTO channels (id, youtube_channel_id, name) VALUES (3, 'UC-wright', 'Wood By Wright');
        INSERT INTO syncs (id, channel_id, status, queued_at, started_at, stage_counts, counted_from)
            VALUES (4, 3, 'running', '2025-01-01', '2025-01-01T00:00:00+00:00', '{}', 2);
        INSERT INTO videos (id, channel_id, youtube_video_id, title, pipeline_stage, discovered_at,
                            failure_stage, failure_reason, failure_permanent, completed_by_sync_id)
            VALUES (11, 3, 'v-one', 'One', 'done', '2025-01-01T00:00:00+00:00', NULL, NULL, NULL, 4),
                   (12, 3, 'v-two', 'Two', 'transcript_fetched', '2025-01-01T00:00:00+00:00', NULL, NULL, NULL, 4);
        """
    )

    # Video 12 failed transiently before a restart and is being fetched again, so it no longer counts as done.
    [resumed] = syncs.get_syncs(conn, [4])
    moved = syncs.update_progress(conn, 4)

    assert moved is not None and resumed.started_at is not None and moved.started_at is not None
    assert (moved.completed_videos, moved.counted_from) == (1, 1)
    assert moved.started_at > resumed.started_at
    conn.close()
