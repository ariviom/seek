import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
import sqlite_vec
from harness import (
    Json,
    add_mentor,
    fake_channel,
    fake_video,
    query,
    row_counts,
    running,
    start_sync,
    wait_for_syncs,
)

from mentor import db
from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import Chapter, Cue


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
    # The query is nearest Rex's Segment, so only filtering before taking the top k finds Wright's.
    nearest_rex = sqlite_vec.serialize_float32(embedder.embed_query("Welcome to Leather sheath"))
    knn = "SELECT segment_id FROM segment_vectors WHERE embedding MATCH ? AND k = 2 AND channel_id = ?"
    wright_hits = [r["segment_id"] for r in query(config, knn, (nearest_rex, wright["channels"][0]["id"]))]
    assert len(wright_hits) == 2 and set(wright_hits) <= {s["id"] for s in segments[:4]}
    assert [r["segment_id"] for r in query(config, knn, (nearest_rex, rex["channels"][0]["id"]))] == [
        segments[4]["id"]
    ]


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
    if completed == "transcript_fetched":
        assert first_ids.isdisjoint(second_ids)
    else:
        assert first_ids == second_ids
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
    attached = await client.post(f"/api/mentors/{wright['id']}/channels", json={"channel": "@wrightvlogs"})
    assert attached.status_code == 201, attached.text
    vlog = attached.json()
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
    # Raises if the FTS5 index still holds terms for deleted Segments.
    query(config, "INSERT INTO segments_fts (segments_fts) VALUES ('integrity-check')")


@dataclass
class BrokenOnGarbledText(FakeEmbedder):
    broken: bool = True

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        if self.broken and any("garbled" in t for t in texts):
            raise ValueError("token sequence too long")
        return super().embed_passages(texts)


async def test_a_video_that_cannot_be_embedded_fails_alone_and_is_retried_on_the_next_sync(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    embedder = BrokenOnGarbledText()
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-garbled", "Garbled", cues=spoken("garbled", until=100)),
        fake_video("v-ok", "Fine"),
    ]
    app = create_app(config, transcripts, embedder, FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        channel_id = mentor["channels"][0]["id"]
        [first] = await sync_all(client, channel_id)
        after_first = (await client.get(f"/api/channels/{channel_id}/videos")).json()
        embedder.broken = False
        second, _ = await sync_all(client, channel_id)
        after_second = (await client.get(f"/api/channels/{channel_id}/videos")).json()

    [garbled] = [v for v in after_first if v["title"] == "Garbled"]
    assert first["status"] == "done"
    assert (first["stage_counts"]["done"], first["stage_counts"]["failed"]) == (1, 1)
    assert (garbled["stage"], garbled["failure_stage"], garbled["permanent_failure"]) == ("failed", "embedded", False)
    assert "token sequence too long" in garbled["reason"]
    assert second["stage_counts"]["done"] == 2
    assert {v["title"]: (v["stage"], v["reason"]) for v in after_second} == {
        "Garbled": ("done", None),
        "Fine": ("done", None),
    }
    assert row_counts(config)["segment_vectors"] == row_counts(config)["segments"] == 3


@pytest.mark.parametrize(
    "changed", [FakeEmbedder(dimension=32), FakeEmbedder(model_name="other-embedder")], ids=["dimension", "model"]
)
async def test_the_embedding_model_can_change_until_vectors_are_stored_then_other_models_are_refused(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, changed: FakeEmbedder
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One"))

    def app(embedder: FakeEmbedder) -> FastAPI:
        return create_app(config, transcripts, embedder, FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")

    async with running(app(FakeEmbedder())):
        pass
    async with running(app(changed)) as client:
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        [synced] = await sync_all(client, mentor["channels"][0]["id"])

    assert synced["status"] == "done"
    refusal = rf"embedded with {changed.model_name} \({changed.dimension} dimensions\)"
    with pytest.raises(RuntimeError, match=refusal):
        async with running(app(FakeEmbedder())):
            pass
    async with running(app(changed)):
        pass
