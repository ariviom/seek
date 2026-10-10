import asyncio
import sqlite3
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
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

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from seek.ports import Chapter, VideoDetails, VideoUnavailable

NO_COUNTS = {
    "discovered": 0,
    "transcript_fetched": 0,
    "segmented": 0,
    "embedded": 0,
    "done": 0,
    "failed": 0,
    "excluded": 0,
}


async def test_a_sync_discovers_videos_and_fetches_their_transcripts_and_metadata(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video(
            "v-dovetails",
            "Hand-cut dovetails",
            source="youtube_auto",
            chapters=[Chapter(title="Marking out", start=0.0, end=45.0), Chapter(title="Sawing", start=45.0, end=600.0)],
        ),
        fake_video("v-planes", "Tuning a hand plane", duration=900, listed_duration=900, published_on=date(2024, 6, 9)),
    ]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    queued = await start_sync(client, channel_id)
    [finished] = await wait_for_syncs(client)
    videos = await list_videos(client, channel_id)

    assert queued["status"] == "queued"
    assert finished["id"] == queued["id"]
    assert finished["status"] == "done"
    assert finished["error"] is None
    assert finished["channel_name"] == "Wood By Wright"
    assert finished["started_at"] is not None and finished["finished_at"] is not None
    assert finished["new_videos"] == 2
    assert finished["stage_counts"] == NO_COUNTS | {"done": 2}
    dovetails = videos["Hand-cut dovetails"]
    assert dovetails == {
        "id": dovetails["id"],
        "youtube_video_id": "v-dovetails",
        "title": "Hand-cut dovetails",
        "published_on": "2025-03-01",
        "duration_seconds": 600,
        "chapters": [
            {"title": "Marking out", "start": 0.0, "end": 45.0},
            {"title": "Sawing", "start": 45.0, "end": 600.0},
        ],
        "stage": "done",
        "reason": None,
        "failure_stage": None,
        "permanent_failure": None,
        "language": "en",
        "transcript_source": "youtube_auto",
    }
    assert videos["Tuning a hand plane"]["published_on"] == "2024-06-09"
    assert videos["Tuning a hand plane"]["transcript_source"] == "youtube_manual"


async def test_videos_under_the_minimum_duration_are_excluded_and_not_processed(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-tip", "Quick tip", listed_duration=90, duration=90),
        fake_video("v-unlisted-length", "Glue-up in a minute", listed_duration=None, duration=60),
        fake_video("v-episode", "Full episode", listed_duration=None, duration=1200),
    ]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    await start_sync(client, channel_id)
    [sync] = await wait_for_syncs(client)
    videos = await list_videos(client, channel_id)

    assert {title: v["stage"] for title, v in videos.items()} == {
        "Quick tip": "excluded",
        "Glue-up in a minute": "excluded",
        "Full episode": "done",
    }
    assert "120" in videos["Quick tip"]["reason"]
    assert videos["Quick tip"]["failure_stage"] is None
    assert videos["Glue-up in a minute"]["duration_seconds"] == 60
    assert "v-tip" not in fetched(transcripts)
    assert sync["status"] == "done"
    assert sync["stage_counts"] == NO_COUNTS | {"done": 1, "excluded": 2}


async def test_unavailable_videos_fail_with_a_reason_and_the_sync_carries_on(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    no_captions_details = VideoDetails(
        video_id="v-silent",
        title="Silent build",
        published_on=date(2024, 1, 2),
        duration_seconds=700,
        description="No talking",
        chapters=[],
    )
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only video", permanent=True)),
        fake_video("v-age", "Axe safety", failure=VideoUnavailable("Age-restricted video", permanent=True)),
        fake_video("v-live", "Live Q&A", failure=VideoUnavailable("Premieres in 3 days", permanent=False)),
        fake_video(
            "v-silent",
            "Silent build",
            failure=VideoUnavailable("No captions", permanent=True, details=no_captions_details),
        ),
        fake_video(
            "v-german",
            "Holzverbindungen",
            failure=VideoUnavailable("Captions are not in English", permanent=True, language="de"),
        ),
        fake_video("v-ok", "Sharpening chisels"),
    ]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    await start_sync(client, channel_id)
    [sync] = await wait_for_syncs(client)
    videos = await list_videos(client, channel_id)

    failures = {
        title: (v["stage"], v["reason"], v["failure_stage"], v["permanent_failure"])
        for title, v in videos.items()
        if title != "Sharpening chisels"
    }
    assert failures == {
        "Members stream": ("failed", "Members-only video", "transcript_fetched", True),
        "Axe safety": ("failed", "Age-restricted video", "transcript_fetched", True),
        "Live Q&A": ("failed", "Premieres in 3 days", "transcript_fetched", False),
        "Silent build": ("failed", "No captions", "transcript_fetched", True),
        "Holzverbindungen": ("failed", "Captions are not in English", "transcript_fetched", True),
    }
    assert videos["Holzverbindungen"]["language"] == "de"
    assert (videos["Silent build"]["published_on"], videos["Silent build"]["duration_seconds"]) == ("2024-01-02", 700)
    assert videos["Sharpening chisels"]["stage"] == "done"
    assert sync["status"] == "done"
    assert sync["stage_counts"] == NO_COUNTS | {"done": 1, "failed": 5}


async def test_a_misbehaving_or_non_english_video_fails_alone_and_transient_failures_are_retried(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    def crash() -> None:
        raise RuntimeError("unexpected extractor output")

    upcoming = fake_video("v-live", "Live Q&A", failure=VideoUnavailable("Premieres in 3 days", permanent=False))
    broken = fake_video("v-broken", "Broken page", before_fetch=crash)
    fake_channel(transcripts, "UC-wright").videos += [
        upcoming,
        broken,
        fake_video("v-german", "Holzverbindungen", language="de"),
        fake_video("v-ok", "Sharpening chisels"),
    ]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    await start_sync(client, channel_id)
    [first] = await wait_for_syncs(client)
    after_first = await list_videos(client, channel_id)
    upcoming.failure = None
    broken.before_fetch = None
    await start_sync(client, channel_id)
    second, _ = await wait_for_syncs(client)
    after_second = await list_videos(client, channel_id)

    assert first["status"] == "done"
    assert (after_first["Broken page"]["stage"], after_first["Broken page"]["permanent_failure"]) == ("failed", False)
    assert "unexpected extractor output" in after_first["Broken page"]["reason"]
    german = after_first["Holzverbindungen"]
    assert (german["stage"], german["permanent_failure"], german["language"]) == ("failed", True, "de")
    assert {title: (v["stage"], v["reason"]) for title, v in after_second.items()} == {
        "Live Q&A": ("done", None),
        "Broken page": ("done", None),
        "Holzverbindungen": ("failed", german["reason"]),
        "Sharpening chisels": ("done", None),
    }
    assert second["stage_counts"] == NO_COUNTS | {"done": 3, "failed": 1}
    assert fetched(transcripts).count("v-german") == 1
    assert fetched(transcripts).count("v-ok") == 1


async def test_the_minimum_duration_is_configurable(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-short", "Short", listed_duration=20, duration=20),
        fake_video("v-medium", "Medium", listed_duration=90, duration=90),
    ]
    app = create_app(
        replace(config, min_duration_seconds=30), transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle"
    )

    async with running(app) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        await wait_for_syncs(client)
        videos = await list_videos(client, channel["id"])

    assert {title: v["stage"] for title, v in videos.items()} == {"Short": "excluded", "Medium": "done"}
    assert "30" in videos["Short"]["reason"]


async def test_rerunning_a_sync_upserts_by_video_id_and_fetches_only_new_videos(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, embedder: FakeEmbedder
) -> None:
    videos_tab = fake_channel(transcripts, "UC-wright").videos
    videos_tab.append(fake_video("v-first", "First video"))
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]
    await start_sync(client, channel_id)
    await wait_for_syncs(client)

    videos_tab.append(fake_video("v-second", "Second video"))
    await start_sync(client, channel_id)
    latest, _ = await wait_for_syncs(client)

    assert latest["new_videos"] == 1
    assert latest["stage_counts"] == NO_COUNTS | {"done": 2}
    assert sorted(await list_videos(client, channel_id)) == ["First video", "Second video"]
    assert fetched(transcripts) == ["v-first", "v-second"]
    # Each passage is embedded with its Video's title as context.
    assert embedder.passages == [
        "First video\nWelcome to First video Let's begin",
        "Second video\nWelcome to Second video Let's begin",
    ]


async def test_discovery_lists_past_streams_too_and_later_syncs_may_stop_at_the_videos_already_known(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    channel = fake_channel(transcripts, "UC-wright")
    channel.videos.append(fake_video("v-first", "First video"))
    channel.streams.append(fake_video("v-stream", "Shop livestream"))
    channel_id = (await add_channel(client, "@woodbywright", "Wood By Wright"))["id"]

    await start_sync(client, channel_id)
    [first] = await wait_for_syncs(client)
    await start_sync(client, channel_id)
    await wait_for_syncs(client)
    retry = await client.post(f"/api/channels/{channel_id}/retry-failed")
    assert retry.status_code == 202, retry.text
    await wait_for_syncs(client)

    assert (first["status"], first["new_videos"]) == ("done", 2)
    assert sorted(await list_videos(client, channel_id)) == ["First video", "Shop livestream"]
    # The first listing knows nothing; the next may stop at known Videos; a retry looks at everything again.
    assert transcripts.listings_known == [frozenset(), frozenset({"v-first", "v-stream"}), frozenset()]


async def test_a_reindex_sync_cuts_and_embeds_the_indexed_videos_again_without_fetching(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, embedder: FakeEmbedder
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-first", "First video"))
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]
    await start_sync(client, channel_id)
    await wait_for_syncs(client)

    response = await client.post(f"/api/channels/{channel_id}/syncs", json={"reindex": True})
    assert response.status_code == 202, response.text
    latest, _ = await wait_for_syncs(client)

    assert (latest["status"], latest["new_videos"], latest["stage_counts"]) == ("done", 0, NO_COUNTS | {"done": 1})
    assert fetched(transcripts) == ["v-first"]
    assert embedder.passages == ["First video\nWelcome to First video Let's begin"] * 2


async def test_syncs_run_one_at_a_time_in_queue_order_and_a_queued_channel_is_queued_once(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-wright", "Wright video", before_fetch=gate))
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-rex", "Rex video"))
    fake_channel(transcripts, "UC-wright-vlog").videos.append(fake_video("v-vlog", "Vlog video"))
    wright = await add_channel(client, "@woodbywright", "Wood By Wright")
    vlog = await add_channel(client, "@wrightvlogs")
    rex = await add_channel(client, "@rexkrueger", "Rex Krueger")

    first = await start_sync(client, wright["id"])
    await gate.wait_entered()
    second = await start_sync(client, rex["id"])
    third = await start_sync(client, vlog["id"])
    second_again = await start_sync(client, rex["id"])
    while_running = {s["id"]: s["status"] for s in (await client.get("/api/syncs")).json()}
    gate.released.set()
    finished = await wait_for_syncs(client)

    assert second_again["id"] == second["id"]
    assert while_running == {first["id"]: "running", second["id"]: "queued", third["id"]: "queued"}
    assert [s["id"] for s in finished] == [third["id"], second["id"], first["id"]]
    assert [s["status"] for s in finished] == ["done", "done", "done"]
    assert fetched(transcripts) == ["v-wright", "v-rex", "v-vlog"]


async def test_syncing_all_queues_every_indexed_channel_once(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-wright", "Wright video", before_fetch=gate))
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-rex", "Rex video"))
    fake_channel(transcripts, "UC-wright-vlog").videos.append(fake_video("v-vlog", "Vlog video"))
    wright = await add_channel(client, "@woodbywright", "Wood By Wright")
    vlog = await add_channel(client, "@wrightvlogs")
    rex = await add_channel(client, "@rexkrueger", "Rex Krueger")
    await client.patch(f"/api/channels/{vlog['id']}", json={"indexed": False})

    running_sync = await start_sync(client, wright["id"])
    await gate.wait_entered()
    rex_queued = await start_sync(client, rex["id"])
    response = await client.post("/api/syncs")
    gate.released.set()
    finished = await wait_for_syncs(client)

    assert response.status_code == 202
    queued = response.json()
    assert [(s["channel_name"], s["status"]) for s in queued] == [("Wood By Wright", "queued"), ("Rex Krueger", "queued")]
    assert queued[1]["id"] == rex_queued["id"]
    assert [(s["channel_name"], s["status"]) for s in finished] == [
        ("Wood By Wright", "done"),
        ("Rex Krueger", "done"),
        ("Wood By Wright", "done"),
    ]
    assert finished[2]["id"] == running_sync["id"]
    assert "v-vlog" not in fetched(transcripts)


async def test_a_channel_deleted_mid_sync_is_skipped_without_leaving_rows(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-rex").videos += [
        fake_video("v-rex-1", "Rex one", before_fetch=gate),
        fake_video("v-rex-2", "Rex two"),
    ]
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-wright", "Wright video"))
    rex = await add_channel(client, "@rexkrueger", "Rex Krueger")
    wright = await add_channel(client, "@woodbywright", "Wood By Wright")

    await start_sync(client, rex["id"])
    await gate.wait_entered()
    wright_sync = await start_sync(client, wright["id"])
    deleted = await client.delete(f"/api/channels/{rex['id']}")
    gate.released.set()
    finished = await wait_for_syncs(client)

    assert deleted.status_code == 204
    assert [(s["id"], s["status"]) for s in finished] == [(wright_sync["id"], "done")]
    assert "v-rex-2" not in fetched(transcripts)
    conn = sqlite3.connect(config.database_path)
    try:
        counts = [conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("videos", "transcripts")]
    finally:
        conn.close()
    assert counts == [1, 1]


async def test_a_sync_stops_with_the_reason_when_youtube_is_unavailable(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    def rate_limited() -> None:
        transcripts.unavailable = "YouTube is rate limiting requests"

    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-one", "One", before_fetch=rate_limited),
        fake_video("v-two", "Two"),
    ]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    await start_sync(client, channel_id)
    [during_fetch] = await wait_for_syncs(client)
    await start_sync(client, channel_id)
    during_listing, _ = await wait_for_syncs(client)

    assert (during_fetch["status"], during_fetch["error"]) == ("failed", "YouTube is rate limiting requests")
    assert (during_listing["status"], during_listing["error"]) == ("failed", "YouTube is rate limiting requests")
    assert {title: v["stage"] for title, v in (await list_videos(client, channel_id)).items()} == {
        "One": "discovered",
        "Two": "discovered",
    }


async def test_unknown_channels_have_no_syncs_or_videos(client: httpx.AsyncClient) -> None:
    responses = [await client.post("/api/channels/999/syncs"), await client.get("/api/channels/999/videos")]

    assert [r.status_code for r in responses] == [404, 404]


async def test_a_sync_waits_while_another_process_holds_the_lease(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One"))
    app = create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle", sync_poll_seconds=0.02)

    async with running(app) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        conn = sqlite3.connect(config.database_path, autocommit=True)
        try:
            conn.execute(
                "INSERT INTO sync_lease (id, holder, expires_at) VALUES (1, 'another process', ?)", (time.time() + 60,)
            )
            sync = await start_sync(client, channel["id"])
            await asyncio.sleep(0.3)
            waiting = [s["status"] for s in (await client.get("/api/syncs")).json()]
            conn.execute("UPDATE sync_lease SET expires_at = ?", (time.time() - 1,))
        finally:
            conn.close()
        [finished] = await wait_for_syncs(client)

    assert waiting == ["queued"]
    assert (finished["id"], finished["status"]) == (sync["id"], "done")


async def test_a_sync_left_running_by_a_stopped_server_resumes_at_startup(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One", before_fetch=gate))

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        sync = await start_sync(client, channel["id"])
        await gate.wait_entered()
    gate.released.set()

    async with running(create_app(config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")) as client:
        [finished] = await wait_for_syncs(client)
        videos = await list_videos(client, channel["id"])

    assert (finished["id"], finished["status"]) == (sync["id"], "done")
    assert videos["One"]["stage"] == "done"
