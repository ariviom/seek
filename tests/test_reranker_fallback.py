"""Search and health remain usable across the production reranker's runtime fallback."""

import asyncio
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from harness import add_channel, add_group, fake_channel, fake_video, running, said, sync

from seek.app import create_app
from seek.config import Config
from seek.devices import DeviceSelection
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeTranscriptSource
from seek.models import CrossEncoderReranker, GpuRunner


@pytest.mark.parametrize("cpu_fails", [False, True])
async def test_first_search_retries_mps_on_cpu_and_reports_degradation_without_losing_citations(
    config: Config,
    transcripts: FakeTranscriptSource,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cpu_fails: bool,
) -> None:
    import huggingface_hub
    import sentence_transformers

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *args, **kwargs: [])
    loaded_devices: list[str] = []

    class Encoder:
        def __init__(self, name: str, *, device: str, **kwargs: Any) -> None:
            self.device = device
            self.calls = 0
            loaded_devices.append(device)

        def predict(self, pairs: list[tuple[str, str]]) -> Any:
            self.calls += 1
            # Both devices warm up successfully; failure occurs on the user's actual search.
            if self.calls > 1 and (self.device == "mps" or cpu_fails):
                raise RuntimeError(f"{self.device} cannot score this request")
            return np.array([2.5] * len(pairs))

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", Encoder)
    reranker = CrossEncoderReranker("test/reranker", GpuRunner(), DeviceSelection("mps", "float32"))
    app = create_app(config, transcripts, FakeEmbedder(), reranker, FakeChatEngine(), static_dir=tmp_path / "none")
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-chisel", "Sharpening a chisel", cues=said("Sharpen the chisel on a stone"))
    )
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-excluded", "Other chisel", cues=said("Sharpen the chisel on a stone"))
    )

    async with running(app) as client:
        wright = await add_channel(client, "@woodbywright", "Wood By Wright")
        rex = await add_channel(client, "@rexkrueger")
        await sync(client, wright, rex)
        group = await add_group(client, "Joinery", wright)
        async with asyncio.timeout(5):
            while True:
                before = (await client.get("/api/health")).json()["models"]
                if before["reranker"]["state"] == "ready":
                    break
                await asyncio.sleep(0.01)
        assert before["reranker"]["device"] == "mps"

        for _ in range(2):
            response = await client.post(
                "/api/search", json={"query": "sharpen chisel", "group": group["id"], "limit": 1}
            )
            assert response.status_code == 200, response.text
            [result] = response.json()
            assert result["youtube_video_id"] == "v-chisel"
            assert result["channel_id"] == wright["id"]
            assert result["channel_name"] == "Wood By Wright"
            assert result["text"] == "Sharpen the chisel on a stone"
            assert result["url"] == "https://www.youtube.com/watch?v=v-chisel&t=0s"
            if cpu_fails:
                assert result["score"] == 0
            else:
                assert result["score"] > 0
            models = (await client.get("/api/health")).json()["models"]
            assert models["embedding"] == before["embedding"]
            assert models["reranker"]["device"] == "cpu"
            assert models["reranker"]["precision"] == "float32"
            assert models["reranker"]["state"] == ("failed" if cpu_fails else "ready")
            assert "mps cannot score this request" in models["reranker"]["fallback_reason"]
            if cpu_fails:
                assert "cpu cannot score this request" in models["reranker"]["error"]
            else:
                assert models["reranker"]["error"] is None
        assert loaded_devices == ["mps", "cpu"]
