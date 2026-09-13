from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from harness import (
    Gate,
    add_mentor,
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
from mentor.fakes import FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import ModelUnavailable, VideoUnavailable


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

    async with running(create_app(config, transcripts, embedder, FakeReranker(), static_dir=tmp_path / "no-bundle")) as client:
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        channel_id = mentor["channels"][0]["id"]
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

    async with running(create_app(config, transcripts, embedder, FakeReranker(), static_dir=tmp_path / "no-bundle")) as client:
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        channel_id = mentor["channels"][0]["id"]
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


async def test_retry_failed_during_a_sync_also_retries_failures_that_sync_records_afterwards(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    gate = Gate()
    members_only = VideoUnavailable("Members-only video", permanent=True)
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-members", "Members stream", before_fetch=gate, failure=members_only)
    )
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
    channel_id = mentor["channels"][0]["id"]

    await start_sync(client, channel_id)
    await gate.wait_entered()
    response = await client.post(f"/api/channels/{channel_id}/retry-failed")
    gate.released.set()
    retried, running_during_retry = await wait_for_syncs(client)

    assert response.status_code == 202
    assert retried["id"] == response.json()["id"]
    assert (running_during_retry["status"], retried["status"]) == ("done", "done")
    assert fetched(transcripts) == ["v-members", "v-members"]

