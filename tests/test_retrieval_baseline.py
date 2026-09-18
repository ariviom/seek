"""Opt-in frozen real-corpus retrieval, without application lifecycle or Sync."""

import asyncio
import importlib.metadata
import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, datetime, tzinfo
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from retrieval_baseline import Manifest, Questions, checksum, configured_snapshot, prepare_snapshot

from mentor.db import Database
from mentor.models import CrossEncoderReranker, GpuRunner, SentenceTransformerEmbedder
from mentor.search import Search

pytestmark = pytest.mark.real_models
FIXTURES = Path(__file__).parent / "fixtures"


async def test_frozen_retrieval_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = configured_snapshot(os.environ)
    if source is None:
        pytest.skip("Set MENTOR_RETRIEVAL_SNAPSHOT to the frozen real-corpus SQLite snapshot to run the baseline")
    manifest_path = FIXTURES / "retrieval-baseline-manifest.json"
    questions_path = FIXTURES / "retrieval-baseline.json"
    manifest = Manifest.model_validate_json(manifest_path.read_text())
    fixture = Questions.model_validate_json(questions_path.read_text())
    working = prepare_snapshot(source, tmp_path / "run.db", manifest)
    output = Path(os.environ.get("MENTOR_RETRIEVAL_RESULTS", str(tmp_path / "retrieval-results.json"))).expanduser()
    if output.resolve() in {source.resolve(), manifest_path.resolve(), questions_path.resolve()}:
        raise ValueError("MENTOR_RETRIEVAL_RESULTS must not overwrite the snapshot or frozen inputs")

    # Resolve immutable cached revisions first; never update a repository's moving main ref.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    import huggingface_hub
    import torch

    if not torch.cuda.is_available():
        pytest.fail("The unchanged baseline requires CUDA; check the GPU/driver before retrying")
    paths = {
        model.model: huggingface_hub.snapshot_download(model.model, revision=model.revision, local_files_only=True)
        for model in (manifest.embedding, manifest.reranker)
    }
    # Production wrappers call the Hub downloader before _open; local paths have already been resolved above.
    # Adapt only that external I/O boundary, leaving the production CUDA loader and inference methods intact.
    def cached_download(repo_id: str, **kwargs: Any) -> Any:
        if repo_id not in paths.values():
            raise ValueError(f"Unexpected model download {repo_id}; only the pinned cache is permitted")
        return [] if kwargs.get("dry_run") else repo_id

    monkeypatch.setattr(huggingface_hub, "snapshot_download", cached_download)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "FrozenDateTime":
            return cls.combine(fixture.reference_date, datetime.min.time(), tzinfo=tz or UTC)

    monkeypatch.setattr("mentor.search.datetime", FrozenDateTime)
    gpu = GpuRunner()
    embedder = SentenceTransformerEmbedder(paths[manifest.embedding.model], manifest.embedding.dimension, gpu)
    reranker = CrossEncoderReranker(paths[manifest.reranker.model], gpu)
    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_files_sha256": {
            str(path.relative_to(FIXTURES.parent.parent)): checksum(path)
            for path in sorted((FIXTURES.parent.parent / "src" / "mentor").glob("*.py"))
        },
        "runner_sha256": checksum(Path(__file__)),
        "runner_inputs_sha256": checksum(FIXTURES.parent / "retrieval_baseline.py"),
        "source_diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD"])).hexdigest(),
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
        "manifest": manifest.model_dump(mode="json"),
        "fixture_sha256": checksum(questions_path),
        "reference_date": fixture.reference_date.isoformat(),
        "retrieval": fixture.retrieval.model_dump(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "hardware": torch.cuda.get_device_name(0),
        "cuda": torch.version.cuda,
        "precision": "bfloat16" if torch.cuda.is_bf16_supported() else "float32",
        "dependencies": {name: importlib.metadata.version(name) for name in (
            "torch", "sentence-transformers", "transformers", "huggingface-hub", "sqlite-vec", "numpy"
        )},
        "questions": [],
        "passed": False,
    }
    try:
        await asyncio.to_thread(embedder.load)
        await asyncio.to_thread(reranker.load)
        for model in (embedder, reranker):
            if model.status().state != "ready":
                pytest.fail(f"Pinned CUDA model failed to load: {model.status().error}")
        search = Search(Database(working), embedder, reranker, fixture.retrieval.temperature, fixture.retrieval.recency)
        for question in fixture.questions:
            row: dict[str, Any] = {"id": question.id, "inputs": question.model_dump(), "passed": False}
            try:
                results = await search.search(
                    question.query, group=question.group, limit=question.limit, prefer_recent=question.prefer_recent
                )
                row["rankings"] = [
                    {"rank": rank, "youtube_video_id": result.youtube_video_id, "segment_id": result.segment_id,
                     "start_seconds": result.start_seconds, "score": result.score}
                    for rank, result in enumerate(results, 1)
                ]
                row["missing_video_ids"] = sorted(set(question.required_video_ids) - {
                    result.youtube_video_id for result in results
                })
                row["passed"] = not row["missing_video_ids"]
            except Exception as error:
                row["error"] = f"{type(error).__name__}: {error}"
            report["questions"].append(row)
        report["passed"] = all(row["passed"] for row in report["questions"])
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["models"] = {"embedding": asdict(embedder.status()), "reranker": asdict(reranker.status())}
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["snapshot_unchanged"] = checksum(source) == manifest.snapshot.sha256
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Retrieval baseline results: {output}")
    assert report["snapshot_unchanged"], "Frozen snapshot changed during the run"
    assert report["passed"], f"Retrieval expectations failed; inspect per-question rankings in {output}"
