"""Model ports with injected Hugging Face / sentence-transformers execution boundaries."""

from typing import Any

import numpy as np
import pytest

from seek.devices import DeviceSelection
from seek.models import CrossEncoderReranker, GpuRunner


def test_mps_warmup_failure_retries_on_cpu_before_reporting_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    import huggingface_hub
    import sentence_transformers

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **kw: [])
    executions: list[str] = []

    class Encoder:
        def __init__(self, name: str, *, device: str, **kwargs: Any) -> None:
            self.device = device

        def predict(self, pairs: list[tuple[str, str]]) -> Any:
            executions.append(self.device)
            if self.device == "mps":
                raise RuntimeError("MPS unsupported operation")
            return np.array([2.5] * len(pairs))

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", Encoder)
    reranker = CrossEncoderReranker("test/reranker", GpuRunner(), DeviceSelection("mps", "float32"))
    reranker.load()
    assert reranker.status().state == "ready"
    assert reranker.status().device == "cpu"
    assert reranker.status().precision == "float32"
    assert "MPS unsupported operation" in (reranker.status().fallback_reason or "")
    assert executions == ["mps", "cpu"]
    assert reranker.score("question", ["passage"]) == [2.5]


@pytest.mark.parametrize("cpu_fails", [False, True])
def test_first_runtime_mps_failure_retries_once_and_reports_a_failed_cpu_retry(
    monkeypatch: pytest.MonkeyPatch, cpu_fails: bool
) -> None:
    import huggingface_hub
    import sentence_transformers

    from seek.ports import ModelUnavailable

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **kw: [])
    devices: list[str] = []

    class Encoder:
        def __init__(self, name: str, *, device: str, **kwargs: Any) -> None:
            self.device = device
            self.calls = 0
            devices.append(device)

        def predict(self, pairs: list[tuple[str, str]]) -> Any:
            self.calls += 1
            if self.calls > 1 and (self.device == "mps" or cpu_fails):
                raise RuntimeError(f"{self.device} cannot score this request")
            return np.array([1.25] * len(pairs))

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", Encoder)
    reranker = CrossEncoderReranker("test/reranker", GpuRunner(), DeviceSelection("mps", "float32"))
    reranker.load()
    assert reranker.status().device == "mps"
    assert reranker.status().state == "ready"
    if cpu_fails:
        for _ in range(2):
            with pytest.raises(ModelUnavailable, match="cpu cannot score"):
                reranker.score("question", ["passage"])
        assert reranker.status().state == "failed"
    else:
        assert reranker.score("question", ["passage"]) == [1.25]
        assert reranker.score("another", ["passage"]) == [1.25]
        assert reranker.status().state == "ready"
    assert reranker.status().device == "cpu"
    assert "mps cannot score" in (reranker.status().fallback_reason or "")
    assert devices == ["mps", "cpu"]


def test_cuda_reranker_oom_is_observably_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    import huggingface_hub
    import sentence_transformers
    import torch

    from seek.ports import GpuOutOfMemory

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **kw: [])
    cleanup: list[bool] = []
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: cleanup.append(True))

    class Encoder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.calls = 0

        def predict(self, pairs: list[tuple[str, str]]) -> Any:
            self.calls += 1
            if self.calls > 1:
                raise torch.OutOfMemoryError("full")
            return np.array([0.0])

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", Encoder)
    reranker = CrossEncoderReranker("test/reranker", GpuRunner(), DeviceSelection("cuda", "bfloat16"))
    reranker.load()
    with pytest.raises(GpuOutOfMemory):
        reranker.score("question", ["passage"])
    assert reranker.status().state == "failed"
    assert cleanup == [True]


@pytest.mark.parametrize("device,precision", [("cuda", "bfloat16"), ("cuda", "float32"), ("mps", "float32"), ("cpu", "float32")])
def test_embedding_keeps_prompts_normalization_and_cuda_oom_video_recovery(
    monkeypatch: pytest.MonkeyPatch, device: Any, precision: Any
) -> None:
    import huggingface_hub
    import sentence_transformers
    import torch

    from seek.models import SentenceTransformerEmbedder
    from seek.ports import GpuOutOfMemory, ModelUnavailable

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **kw: [])
    cleanup: list[bool] = []
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: cleanup.append(True))
    loaded: list[dict[str, Any]] = []
    encoded: list[tuple[str, bool]] = []

    class Encoder:
        def __init__(self, name: str, **kwargs: Any) -> None:
            loaded.append(kwargs)

        def get_embedding_dimension(self) -> int:
            return 2

        def encode_document(self, texts: list[str], *, normalize_embeddings: bool) -> Any:
            encoded.append(("document", normalize_embeddings))
            return np.array([[0.6, 0.8]] * len(texts))

        def encode_query(self, text: str, *, normalize_embeddings: bool) -> Any:
            encoded.append(("query", normalize_embeddings))
            if text == "out of memory":
                raise torch.OutOfMemoryError("allocation failed")
            return np.array([0.6, 0.8])

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", Encoder)
    embedder = SentenceTransformerEmbedder("test/embedding", 2, GpuRunner(), DeviceSelection(device, precision))
    embedder.load()
    assert embedder.status().state == "ready"
    assert loaded == [{"device": device, "local_files_only": True,
                       "model_kwargs": {"dtype": torch.bfloat16 if precision == "bfloat16" else torch.float32}}]
    assert embedder.embed_passages(["passage"])[0] == pytest.approx([0.6, 0.8])
    assert embedder.embed_query("question") == pytest.approx([0.6, 0.8])
    assert encoded == [("document", True), ("query", True)]
    with pytest.raises(GpuOutOfMemory if device == "cuda" else ModelUnavailable):
        embedder.embed_query("out of memory")
    assert cleanup == ([True] if device == "cuda" else [])
    assert embedder.status().state == ("ready" if device == "cuda" else "failed")
    if device == "cuda":
        assert embedder.embed_query("retry") == pytest.approx([0.6, 0.8])


@pytest.mark.parametrize("cpu_fails", [False, True])
def test_mps_constructor_failure_tries_cpu_and_never_invokes_cuda_cleanup(
    monkeypatch: pytest.MonkeyPatch, cpu_fails: bool
) -> None:
    import huggingface_hub
    import sentence_transformers
    import torch

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **kw: [])
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: pytest.fail("Non-CUDA models must not clean up CUDA"))
    devices: list[str] = []

    class Encoder:
        def __init__(self, name: str, *, device: str, **kwargs: Any) -> None:
            devices.append(device)
            if device == "mps" or cpu_fails:
                raise torch.OutOfMemoryError(f"{device} allocation failed")

        def predict(self, pairs: list[tuple[str, str]]) -> Any:
            return np.array([0.0] * len(pairs))

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", Encoder)
    reranker = CrossEncoderReranker("test/reranker", GpuRunner(), DeviceSelection("mps", "float32"))
    reranker.load()
    assert reranker.status().state == ("failed" if cpu_fails else "ready")
    assert reranker.status().device == "cpu"
    assert devices == ["mps", "cpu"]
    assert "mps allocation failed" in (reranker.status().fallback_reason or "")
    if cpu_fails:
        assert "cpu allocation failed" in (reranker.status().error or "")


@pytest.mark.parametrize("cache_complete", [False, True])
def test_offline_cached_model_loads_or_explains_missing_cache(
    monkeypatch: pytest.MonkeyPatch, cache_complete: bool
) -> None:
    import huggingface_hub
    import sentence_transformers
    from huggingface_hub.errors import DryRunError, LocalEntryNotFoundError

    def download(name: str, **kwargs: Any) -> Any:
        if kwargs.get("dry_run"):
            raise DryRunError("offline")
        if not cache_complete:
            raise LocalEntryNotFoundError("No cached snapshot")
        return "/cached/snapshot"

    class Encoder:
        def __init__(self, name: str, **kwargs: Any) -> None:
            assert kwargs["local_files_only"] is True

        def predict(self, pairs: list[tuple[str, str]]) -> Any:
            return np.array([0.25] * len(pairs))

    monkeypatch.setattr(huggingface_hub, "snapshot_download", download)
    monkeypatch.setattr(sentence_transformers, "CrossEncoder", Encoder)
    reranker = CrossEncoderReranker("test/reranker", GpuRunner(), DeviceSelection("cpu", "float32"))
    reranker.load()
    if cache_complete:
        assert reranker.score("question", ["passage"]) == [0.25]
        assert reranker.status().state == "ready"
    else:
        assert reranker.status().state == "failed"
        assert "restart seek once online" in (reranker.status().error or "")


def test_download_progress_keeps_byte_totals_and_selected_device(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import huggingface_hub
    import sentence_transformers

    from seek.ports import ModelStatus

    observed: list[ModelStatus] = []

    def download(name: str, **kwargs: Any) -> Any:
        if kwargs.get("dry_run"):
            return [SimpleNamespace(file_size=1200, will_download=True)]
        observed.append(reranker.status())
        with kwargs["tqdm_class"](total=1200, desc="Reconstruct model", unit="B", leave=False) as progress:
            progress.update(340)
            observed.append(reranker.status())
        return "/cached/snapshot"

    class Encoder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def predict(self, pairs: list[tuple[str, str]]) -> Any:
            return np.array([0.0] * len(pairs))

    monkeypatch.setattr(huggingface_hub, "snapshot_download", download)
    monkeypatch.setattr(sentence_transformers, "CrossEncoder", Encoder)
    reranker = CrossEncoderReranker("test/reranker", GpuRunner(), DeviceSelection("cpu", "float32"))
    reranker.load()
    assert [(s.state, s.downloaded_bytes, s.total_bytes, s.device, s.precision) for s in observed] == [
        ("downloading", 0, 1200, "cpu", "float32"),
        ("downloading", 340, 1200, "cpu", "float32"),
    ]
    assert reranker.status().state == "ready"
