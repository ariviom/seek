"""Actual local model execution; select explicitly with -m real_models.

SEEK_VERIFY_DEVICE=cpu exercises CPU even when an accelerator is available.
SEEK_DEVICE_RESULTS writes portable verification evidence outside the checkout.
"""

import asyncio
import importlib.metadata
import json
import math
import os
import platform
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from seek.config import DEFAULT_EMBEDDING_DIMENSION, DEFAULT_EMBEDDING_MODEL, DEFAULT_RERANKER_MODEL
from seek.devices import DeviceSelection, probe_device, select_device
from seek.models import CrossEncoderReranker, GpuRunner, SentenceTransformerEmbedder

pytestmark = pytest.mark.real_models


async def test_real_models_embed_and_score_on_the_selected_device(tmp_path: Path) -> None:
    requested = os.environ.get("SEEK_VERIFY_DEVICE", "auto")
    assert requested in {"auto", "cpu"}, "SEEK_VERIFY_DEVICE must be auto or cpu"
    probe = probe_device()
    selection = DeviceSelection("cpu", "float32") if requested == "cpu" else select_device(probe)
    runner = GpuRunner()
    embedder = SentenceTransformerEmbedder(DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_DIMENSION, runner, selection)
    reranker = CrossEncoderReranker(DEFAULT_RERANKER_MODEL, runner, selection)
    output = Path(os.environ.get("SEEK_DEVICE_RESULTS", str(tmp_path / "device-results.json")))
    report: dict[str, object] = {
        "started_at": datetime.now(UTC).isoformat(),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
        "platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
        "probe": asdict(probe), "selection": asdict(selection), "requested": requested,
        "dependencies": {name: importlib.metadata.version(name) for name in (
            "torch", "sentence-transformers", "transformers", "huggingface-hub", "numpy"
        )},
        "passed": False,
    }
    import torch
    from huggingface_hub import snapshot_download

    report["hardware"] = (
        subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        if platform.system() == "Darwin" else platform.processor()
    )
    if selection.device == "cuda":
        report["hardware"] = torch.cuda.get_device_name(0)
    report["cuda"] = torch.version.cuda
    report["torch_threads"] = torch.get_num_threads()
    report["offline"] = {name: os.environ.get(name) for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
    try:
        await asyncio.to_thread(embedder.load)
        await asyncio.to_thread(reranker.load)
        assert embedder.status().state == "ready", embedder.status()
        assert reranker.status().state == "ready", reranker.status()
        passages = ["Cut dovetail joints with a saw and a sharp chisel.", "Charge the cordless drill battery overnight."]
        query = "How do I cut dovetail joints?"
        vectors = await asyncio.to_thread(embedder.embed_passages, passages)
        vector = await asyncio.to_thread(embedder.embed_query, query)
        logits = await asyncio.to_thread(reranker.score, query, passages)
        assert len(vectors) == 2 and len(logits) == 2
        assert all(len(v) == DEFAULT_EMBEDDING_DIMENSION for v in [*vectors, vector])
        assert all(math.isfinite(x) for v in [*vectors, vector] for x in v)
        norms = [math.sqrt(sum(x * x for x in v)) for v in [*vectors, vector]]
        assert all(abs(norm - 1) < 0.02 for norm in norms)
        assert all(math.isfinite(logit) for logit in logits)
        assert logits[0] > logits[1], logits
        report.update(vector_dimension=len(vector), vector_norms=norms, logits=logits, passed=True)
        report["model_revisions"] = {
            name: Path(snapshot_download(name, local_files_only=True)).name
            for name in (DEFAULT_EMBEDDING_MODEL, DEFAULT_RERANKER_MODEL)
        }
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["models"] = {"embedding": asdict(embedder.status()), "reranker": asdict(reranker.status())}
        report["finished_at"] = datetime.now(UTC).isoformat()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Device verification results: {output}")
