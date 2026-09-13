import json
from pathlib import Path

import httpx
import pytest
import sqlite_vec
from harness import Json, add_mentor, fake_video, query, row_counts, running, start_sync, wait_for_syncs

from mentor import db
from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChannel, FakeEmbedder, FakeTranscriptSource
from mentor.ports import Chapter, Cue


def fake_channel(transcripts: FakeTranscriptSource, youtube_channel_id: str) -> FakeChannel:
    [channel] = [c for c in transcripts.channels if c.info.channel_id == youtube_channel_id]
    return channel


def spoken(topic: str, until: float) -> list[Cue]:
    return [Cue(start=i * 5.0, end=(i + 1) * 5.0, text=f"{topic} step {i}") for i in range(round(until / 5))]


async def sync_all(client: httpx.AsyncClient, *channel_ids: int) -> list[Json]:
    for channel_id in channel_ids:
        await start_sync(client, channel_id)
    return await wait_for_syncs(client)


async def test_a_sync_segments_and_embeds_videos_into_indexes_that_knn_can_scope_by_channel(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, embedder: FakeEmbedder, config: Config
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video(
            "v-dovetails",
            "Hand-cut dovetails",
            cues=spoken("dovetail", until=200),
            chapters=[Chapter(title="Marking out", start=0, end=100), Chapter(title="Sawing", start=100, end=200)],
        )
    )
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-sheath", "Leather sheath"))
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")

    finished = await sync_all(client, wright["channels"][0]["id"], rex["channels"][0]["id"])

    assert [(s["status"], s["stage_counts"]["done"]) for s in finished] == [("done", 1), ("done", 1)]
    segments = query(
        config,
        """
        SELECT segments.*, videos.youtube_video_id FROM segments JOIN videos ON videos.id = segments.video_id
        ORDER BY segments.id
        """,
    )
    assert [(s["youtube_video_id"], s["start_seconds"], s["end_seconds"], s["chapter_title"]) for s in segments] == [
        ("v-dovetails", 0, 90, "Marking out"),
        ("v-dovetails", 40, 100, "Marking out"),
        ("v-dovetails", 100, 190, "Sawing"),
        ("v-dovetails", 140, 200, "Sawing"),
        ("v-sheath", 0, 9.5, None),
    ]
    assert segments[4]["text"] == "Welcome to Leather sheath Let's begin"
    assert json.loads(segments[4]["cues"]) == [{"start": 0.0, "offset": 0}, {"start": 4.0, "offset": 26}]
    assert row_counts(config) == {
        "videos": 2,
        "transcripts": 2,
        "segments": 5,
        "segments_fts_docsize": 5,
        "segment_vectors": 5,
    }
    [lexical] = query(config, "SELECT rowid FROM segments_fts WHERE segments_fts MATCH 'sheath'")
    assert lexical["rowid"] == segments[4]["id"]
    nearest = sqlite_vec.serialize_float32(embedder.embed_query("Leather sheath"))
    knn = "SELECT segment_id FROM segment_vectors WHERE embedding MATCH ? AND k = 10 AND channel_id = ?"
    assert {r["segment_id"] for r in query(config, knn, (nearest, wright["channels"][0]["id"]))} == {
        s["id"] for s in segments[:4]
    }
    assert [r["segment_id"] for r in query(config, knn, (nearest, rex["channels"][0]["id"]))] == [segments[4]["id"]]


async def test_an_embedding_failure_stops_the_sync_and_the_rerun_embeds_without_duplicates(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, embedder: FakeEmbedder, config: Config
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-one", "One", cues=spoken("one", until=300)),
        fake_video("v-two", "Two"),
    ]
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
    channel_id = mentor["channels"][0]["id"]

    embedder.unavailable = "CUDA out of memory"
    [failed] = await sync_all(client, channel_id)
    after_failure = row_counts(config)
    embedder.unavailable = None
    rerun, _ = await sync_all(client, channel_id)

    assert (failed["status"], failed["error"]) == ("failed", "CUDA out of memory")
    assert failed["stage_counts"]["segmented"] == 1
    assert (after_failure["segments"], after_failure["segment_vectors"]) == (4, 0)
    assert rerun["status"] == "done"
    assert rerun["stage_counts"]["done"] == 2
    assert row_counts(config) == {
        "videos": 2,
        "transcripts": 2,
        "segments": 5,
        "segments_fts_docsize": 5,
        "segment_vectors": 5,
    }


@pytest.mark.parametrize("completed", ["transcript_fetched", "segmented"])
async def test_rerunning_a_stage_for_a_video_replaces_its_segments_and_vectors(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config, completed: str
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One", cues=spoken("one", until=300)))
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
    channel_id = mentor["channels"][0]["id"]
    await sync_all(client, channel_id)
    first_ids = {r["id"] for r in query(config, "SELECT id FROM segments")}

    # Stands in for a retry that sends a finished Video back through a stage.
    conn = db.connect(config.database_path)
    try:
        conn.execute("UPDATE videos SET pipeline_stage = ?", (completed,))
    finally:
        conn.close()
    [rerun, _] = await sync_all(client, channel_id)

    assert rerun["stage_counts"]["done"] == 1
    second_ids = {r["id"] for r in query(config, "SELECT id FROM segments")}
    assert len(second_ids) == len(first_ids) == 4
    assert first_ids.isdisjoint(second_ids) if completed == "transcript_fetched" else first_ids == second_ids
    vectors = query(config, "SELECT segment_id FROM segment_vectors ORDER BY segment_id")
    assert [r["segment_id"] for r in vectors] == sorted(second_ids)
    assert row_counts(config)["segments_fts_docsize"] == 4


async def test_deleting_a_channel_or_mentor_removes_its_videos_transcripts_segments_and_vectors(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-main", "Main", cues=spoken("main", until=200)))
    fake_channel(transcripts, "UC-wright-vlog").videos.append(fake_video("v-vlog", "Vlog"))
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-rex", "Rex", cues=spoken("rex", until=150)))
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    vlog = (await client.post(f"/api/mentors/{wright['id']}/channels", json={"channel": "@wrightvlogs"})).json()
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")
    await sync_all(client, wright["channels"][0]["id"], vlog["id"], rex["channels"][0]["id"])
    synced = row_counts(config)

    detached = await client.delete(f"/api/channels/{vlog['id']}")
    after_detach = row_counts(config)
    deleted = [await client.delete(f"/api/mentors/{wright['id']}"), await client.delete(f"/api/mentors/{rex['id']}")]

    assert synced == {"videos": 3, "transcripts": 3, "segments": 6, "segments_fts_docsize": 6, "segment_vectors": 6}
    assert [r.status_code for r in (detached, *deleted)] == [204, 204, 204]
    assert after_detach == {
        "videos": 2,
        "transcripts": 2,
        "segments": 5,
        "segments_fts_docsize": 5,
        "segment_vectors": 5,
    }
    assert row_counts(config) == dict.fromkeys(synced, 0)


@pytest.mark.parametrize(
    "changed", [FakeEmbedder(dimension=32), FakeEmbedder(model_name="other-embedder")], ids=["dimension", "model"]
)
async def test_server_refuses_a_knowledge_base_embedded_with_a_different_model(
    config: Config, tmp_path: Path, changed: FakeEmbedder
) -> None:
    async with running(create_app(config, FakeTranscriptSource(), FakeEmbedder(), static_dir=tmp_path / "none")):
        pass

    with pytest.raises(RuntimeError, match="embedded with fake-embedder \\(64 dimensions\\)"):
        async with running(create_app(config, FakeTranscriptSource(), changed, static_dir=tmp_path / "none")):
            pass
    async with running(create_app(config, FakeTranscriptSource(), FakeEmbedder(), static_dir=tmp_path / "none")):
        pass
