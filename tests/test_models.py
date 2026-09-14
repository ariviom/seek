from pathlib import Path

import pytest
from harness import Gate, add_mentor, event_stream, fake_channel, fake_video, running, start_sync, wait_for_syncs

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import ModelStatus


async def test_models_load_in_the_background_while_health_and_events_report_their_progress(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    gate = Gate()
    downloading = ModelStatus("fake-embedder", "downloading", downloaded_bytes=340, total_bytes=1200)
    embedder = FakeEmbedder(before_load=gate, status_while_loading=downloading)
    app = create_app(
        config, transcripts, embedder, FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle", model_progress_seconds=0.02
    )

    async with running(app) as client, event_stream(app) as events:
        await gate.wait_entered()
        loading = (await client.get("/api/health")).json()["models"]
        gate.released.set()
        published = await events.until(
            lambda e: e["type"] == "models" and all(m["state"] == "ready" for m in e["models"].values())
        )
        after = (await client.get("/api/health")).json()["models"]

    assert loading == {
        "embedding": {
            "name": "fake-embedder",
            "state": "downloading",
            "downloaded_bytes": 340,
            "total_bytes": 1200,
            "error": None,
        },
        # Models load one at a time.
        "reranker": {
            "name": "fake-reranker",
            "state": "waiting",
            "downloaded_bytes": None,
            "total_bytes": None,
            "error": None,
        },
    }
    assert after == published[-1]["models"]


async def test_search_answers_models_loading_and_syncs_wait_until_the_embedding_model_is_ready(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One"))
    embedder = FakeEmbedder(before_load=gate)
    app = create_app(
        config, transcripts, embedder, FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle", sync_poll_seconds=0.02
    )

    async with running(app) as client:
        await gate.wait_entered()
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        await start_sync(client, mentor["channels"][0]["id"])
        search = await client.post("/api/search", json={"query": "welcome"})
        with pytest.raises(TimeoutError):
            await wait_for_syncs(client, timeout=0.2)
        gate.released.set()
        [finished] = await wait_for_syncs(client)

    assert (search.status_code, search.json()["detail"]) == (
        503,
        "The model fake-embedder is still loading; try again shortly",
    )
    assert (finished["status"], finished["stage_counts"]["done"]) == ("done", 1)


async def test_an_embedding_model_that_fails_to_load_fails_syncs_before_any_youtube_calls(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One"))
    embedder = FakeEmbedder(load_error="The GPU ran out of memory loading fake-embedder")
    app = create_app(config, transcripts, embedder, FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        await start_sync(client, mentor["channels"][0]["id"])
        [failed] = await wait_for_syncs(client)
        health = (await client.get("/api/health")).json()["models"]["embedding"]
        search = await client.post("/api/search", json={"query": "welcome"})

    assert (health["state"], health["error"]) == ("failed", "The GPU ran out of memory loading fake-embedder")
    assert (failed["status"], failed["error"]) == ("failed", "The GPU ran out of memory loading fake-embedder")
    assert [method for method, _ in transcripts.calls] == ["resolve_channel"]
    assert (search.status_code, search.json()["detail"]) == (503, "The GPU ran out of memory loading fake-embedder")


async def test_a_reranking_model_that_fails_to_load_stops_search_but_not_syncs(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One"))
    reranker = FakeReranker(load_error="Hugging Face has no model named fake-reranker")
    app = create_app(config, transcripts, FakeEmbedder(), reranker, FakeChatEngine(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
        await start_sync(client, mentor["channels"][0]["id"])
        [synced] = await wait_for_syncs(client)
        search = await client.post("/api/search", json={"query": "welcome"})

    assert (synced["status"], synced["stage_counts"]["done"]) == ("done", 1)
    assert (search.status_code, search.json()["detail"]) == (503, "Hugging Face has no model named fake-reranker")
