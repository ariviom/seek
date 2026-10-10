from pathlib import Path

import pytest
from harness import Gate, add_channel, event_stream, fake_channel, fake_video, running, start_sync, wait_for_syncs

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from seek.ports import ModelStatus


async def test_model_events_continue_reporting_failures_after_startup(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    class RuntimeReranker(FakeReranker):
        runtime_status: ModelStatus | None = None

        def status(self) -> ModelStatus:
            return self.runtime_status or super().status()

    gate = Gate()
    reranker = RuntimeReranker(before_load=gate)
    app = create_app(
        config, transcripts, FakeEmbedder(), reranker, FakeChatEngine(),
        static_dir=tmp_path / "none", model_progress_seconds=0.01,
    )
    async with running(app) as client, event_stream(app) as events:
        await gate.wait_entered()
        gate.released.set()
        await events.until(lambda e: e["type"] == "models" and e["models"]["reranker"]["state"] == "ready")
        reranker.runtime_status = ModelStatus(
            "fake-reranker", "ready", device="cpu", precision="float32", fallback_reason="MPS scoring unsupported"
        )
        fallback = await events.until(
            lambda e: e["type"] == "models" and e["models"]["reranker"]["device"] == "cpu", timeout=0.5
        )
        assert fallback[-1]["models"] == (await client.get("/api/health")).json()["models"]
        reranker.runtime_status = ModelStatus(
            "fake-reranker", "failed", error="CPU scoring failed", device="cpu", precision="float32",
            fallback_reason="MPS scoring unsupported",
        )
        changed = await events.until(
            lambda e: e["type"] == "models" and e["models"]["reranker"]["state"] == "failed", timeout=0.5
        )
        health = (await client.get("/api/health")).json()["models"]
    assert changed[-1]["models"] == health
    assert health["reranker"]["error"] == "CPU scoring failed"


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
            "device": None,
            "precision": None,
            "fallback_reason": None,
        },
        # Models load one at a time.
        "reranker": {
            "name": "fake-reranker",
            "state": "waiting",
            "downloaded_bytes": None,
            "total_bytes": None,
            "error": None,
            "device": None,
            "precision": None,
            "fallback_reason": None,
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
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
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
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        [failed] = await wait_for_syncs(client)
        health = (await client.get("/api/health")).json()["models"]["embedding"]
        search = await client.post("/api/search", json={"query": "welcome"})

    assert (health["state"], health["error"]) == ("failed", "The GPU ran out of memory loading fake-embedder")
    assert (failed["status"], failed["error"]) == ("failed", "The GPU ran out of memory loading fake-embedder")
    assert [method for method, _ in transcripts.calls] == ["resolve_channel"]
    assert (search.status_code, search.json()["detail"]) == (503, "The GPU ran out of memory loading fake-embedder")


async def test_a_reranking_model_that_fails_to_load_preserves_fused_search_and_syncs(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One"))
    reranker = FakeReranker(load_error="Hugging Face has no model named fake-reranker")
    app = create_app(config, transcripts, FakeEmbedder(), reranker, FakeChatEngine(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        [synced] = await wait_for_syncs(client)
        search = await client.post("/api/search", json={"query": "welcome"})

    assert (synced["status"], synced["stage_counts"]["done"]) == ("done", 1)
    assert search.status_code == 200
    assert [(result["youtube_video_id"], result["score"]) for result in search.json()] == [("v-one", 0.0)]
