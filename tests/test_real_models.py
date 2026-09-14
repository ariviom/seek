"""With the configured models on the GPU, downloading them on first run; run with `uv run pytest -m real_models`."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from harness import Json, add_channel, fake_channel, fake_video, running, start_sync, wait_for_syncs

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeTranscriptSource
from mentor.models import CrossEncoderReranker, GpuRunner, SentenceTransformerEmbedder
from mentor.ports import Cue

pytestmark = pytest.mark.real_models


async def wait_for_models(client: httpx.AsyncClient, timeout: float = 900) -> Json:
    async with asyncio.timeout(timeout):
        while True:
            models: Json = (await client.get("/api/health")).json()["models"]
            if all(m["state"] in ("ready", "failed") for m in models.values()):
                return models
            await asyncio.sleep(0.5)


def spoken(*lines: str) -> list[Cue]:
    return [Cue(start=i * 6.0, end=(i + 1) * 6.0, text=line) for i, line in enumerate(lines)]


async def test_the_real_models_rank_a_planted_segment_first_and_recency_only_breaks_ties(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    today = datetime.now(UTC).date()
    how_to = spoken(
        "To cut the dovetails, knife a baseline all the way round the board.",
        "Saw down to the line on the waste side, keeping the kerf in the waste.",
        "Then chop the waste out with a chisel, working in from both faces.",
    )
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-dovetails", "Hand-cut joinery", published_on=today - timedelta(days=365), cues=how_to),
        # The same advice, a decade older.
        fake_video("v-dovetails-old", "Joinery basics", published_on=today - timedelta(days=3650), cues=how_to),
        fake_video(
            "v-drill",
            "Tool review",
            published_on=today,
            cues=spoken("This cordless drill has plenty of torque.", "The battery lasted all day in the shop."),
        ),
        fake_video(
            "v-finish",
            "Finishing",
            cues=spoken("Wipe on a thin coat of oil.", "Let it cure overnight before a second coat on the joint."),
        ),
        fake_video(
            "v-clamps",
            "Glue-ups",
            cues=spoken("Dry fit the joints first.", "Then clamp the frame square and check the diagonals."),
        ),
    ]
    gpu = GpuRunner()
    embedder = SentenceTransformerEmbedder(config.embedding_model, config.embedding_dimension, gpu)
    reranker = CrossEncoderReranker(config.reranker_model, gpu)
    app = create_app(config, transcripts, embedder, reranker, FakeChatEngine(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        models = await wait_for_models(client)
        channel = await add_channel(client, "@woodbywright", "Wood By Wright")
        await start_sync(client, channel["id"])
        [synced] = await wait_for_syncs(client, timeout=120)
        gentle = await client.post("/api/search", json={"query": "how do I cut dovetails by hand?"})
        strong = await client.post(
            "/api/search", json={"query": "how do I cut dovetails by hand?", "prefer_recent": "strong"}
        )
        logits = await asyncio.to_thread(
            reranker.score, "how do I cut dovetails by hand?", ["Chop the waste out with a chisel.", "Charge the drill."]
        )

    assert {role: (m["state"], m["error"]) for role, m in models.items()} == {
        "embedding": ("ready", None),
        "reranker": ("ready", None),
    }
    # Raw logits, not probabilities: search applies the sigmoid itself.
    assert logits[0] > logits[1] and min(logits) < 0
    assert synced["status"] == "done", synced["error"]
    assert (gentle.status_code, strong.status_code) == (200, 200), (gentle.text, strong.text)
    ranked = {
        level: [r["youtube_video_id"] for r in response.json()] for level, response in (("gentle", gentle), ("strong", strong))
    }
    # The newer copy wins the tie; even strongly preferring newer Videos, a brand-new irrelevant one doesn't win.
    assert ranked["gentle"][:2] == ["v-dovetails", "v-dovetails-old"], gentle.json()
    assert ranked["strong"].index("v-dovetails-old") < ranked["strong"].index("v-drill"), strong.json()
