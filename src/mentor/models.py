"""The embedding and reranking models, run with sentence-transformers on the GPU.

Models download from Hugging Face on first use and are cached there. torch and sentence-transformers are imported only
when a model loads, so commands and tests that don't need them start quickly.
"""

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Literal

from tqdm.auto import tqdm

from mentor.ports import ModelStatus, ModelUnavailable

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder, SentenceTransformer

log = logging.getLogger(__name__)

_MEGABYTE = 1_000_000
# Formats sentence-transformers doesn't load; some repositories ship several gigabytes of ONNX or OpenVINO exports.
_UNUSED_FILES = ["onnx/*", "openvino/*", "*.onnx", "*.h5", "*.msgpack", "*.ot", "tf_model*", "flax_model*", "rust_model*"]


class GpuRunner:
    """Runs every model call on one thread: the models aren't safe to call concurrently, and calls would contend
    for GPU memory anyway."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mentor-gpu")

    def run[T](self, work: Callable[[], T]) -> T:
        return self._executor.submit(work).result()


class _LoadRefused(Exception):
    """The model can't be used as configured; the message is for the user."""


class _HubModel[M]:
    """A Hugging Face model that downloads and loads in load(), then runs its calls on the GPU thread."""

    def __init__(self, name: str, role: Literal["embedding", "reranking"], gpu: GpuRunner) -> None:
        self._name = name
        self._role = role
        self._gpu = gpu
        self._model: M | None = None
        # Replaced whole, never mutated, so readers on other threads see a consistent status.
        self._status = ModelStatus(name, "waiting")

    def status(self) -> ModelStatus:
        return self._status

    def load(self) -> None:
        try:
            self._download()
            self._status = ModelStatus(self._name, "loading")
            self._model = self._gpu.run(self._open)
            self._status = ModelStatus(self._name, "ready")
        except Exception as e:
            try:
                message = self._expected_failure(e)
            except Exception:
                # e.g. torch itself can't be imported; the original error is the one worth reporting.
                message = None
            if message is None:
                log.exception("Loading %s failed", self._name)
                message = f"Could not load the {self._role} model {self._name}: {e}"
            self._status = ModelStatus(self._name, "failed", error=message)

    def _expected_failure(self, error: Exception) -> str | None:
        """A message for the user if this is a failure worth no traceback."""
        import torch
        from huggingface_hub.errors import GatedRepoError, LocalEntryNotFoundError, RepositoryNotFoundError

        if isinstance(error, _LoadRefused):
            return str(error)
        if isinstance(error, torch.OutOfMemoryError):
            torch.cuda.empty_cache()
            return (
                f"The GPU ran out of memory loading the {self._role} model {self._name}; free GPU memory used by "
                "other programs and restart mentor"
            )
        if isinstance(error, GatedRepoError):
            return (
                f"The {self._role} model {self._name} is gated on Hugging Face; accept its terms and log in with "
                "`hf auth login`, then restart mentor"
            )
        if isinstance(error, RepositoryNotFoundError):
            return f"Hugging Face has no model named {self._name}; check the configured {self._role} model"
        if isinstance(error, LocalEntryNotFoundError):
            return (
                f"The {self._role} model {self._name} isn't downloaded yet and Hugging Face can't be reached; "
                "restart mentor once online"
            )
        return None

    def _download(self) -> None:
        """Fetches whatever isn't cached yet, reporting progress; with no network, a complete cache is enough."""
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import DryRunError

        try:
            planned = snapshot_download(self._name, ignore_patterns=_UNUSED_FILES, dry_run=True)
        except DryRunError:
            # The Hub can't be reached; the download below falls back to the cache, or explains what's missing.
            planned = []
        missing = sum(f.file_size or 0 for f in planned if f.will_download)
        if missing:
            self._status = ModelStatus(self._name, "downloading", downloaded_bytes=0, total_bytes=missing)
        snapshot_download(self._name, ignore_patterns=_UNUSED_FILES, tqdm_class=self._progress_bar(missing))

    def _progress_bar(self, total: int) -> "type[tqdm[object]]":
        report = self._report_download

        class Progress(tqdm):  # type: ignore[type-arg]
            def update(self, n: float | None = 1) -> bool | None:
                shown: bool | None = super().update(n)
                # Bytes written to disk add up to the file sizes; bytes received may be fewer, being compressed.
                if total and self.unit == "B" and str(self.desc).startswith("Reconstruct"):
                    report(int(self.n), total)
                return shown

        # A plain tqdm rather than Hugging Face's, which stops counting when there is no terminal (as under systemd).
        return Progress

    def _report_download(self, downloaded: int, total: int) -> None:
        self._status = ModelStatus(self._name, "downloading", downloaded_bytes=min(downloaded, total), total_bytes=total)

    def _open(self) -> M:
        raise NotImplementedError

    def _call[T](self, work: Callable[[M], T]) -> T:
        model = self._model
        if model is None:
            raise ModelUnavailable(self._not_ready())

        def on_gpu() -> T:
            import torch

            try:
                return work(model)
            except torch.OutOfMemoryError:
                torch.cuda.empty_cache()
                raise ModelUnavailable(
                    f"The GPU ran out of memory running the {self._role} model {self._name}; free GPU memory used by "
                    "other programs and try again"
                ) from None

        return self._gpu.run(on_gpu)

    def _not_ready(self) -> str:
        status = self._status
        subject = f"The {self._role} model {self._name}"
        if status.state == "failed" and status.error is not None:
            return status.error
        if status.state == "downloading":
            done = (status.downloaded_bytes or 0) // _MEGABYTE
            of = "" if status.total_bytes is None else f" of {status.total_bytes // _MEGABYTE}"
            return f"{subject} is downloading ({done}{of} MB); try again once it has loaded"
        return f"{subject} is still loading; try again shortly"


def _cuda_dtype(name: str) -> object:
    import torch

    if not torch.cuda.is_available():
        raise _LoadRefused(f"No CUDA GPU is available to run {name}; check the NVIDIA driver and CUDA_VISIBLE_DEVICES")
    # The Qwen-based defaults are trained in bfloat16, and float16 can overflow them; float32 needs twice the memory.
    return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float32


class SentenceTransformerEmbedder(_HubModel["SentenceTransformer"]):
    """Queries carry the model's query prompt; passages get its document prompt, which the default model leaves
    empty. Vectors are L2-normalised."""

    def __init__(self, model_name: str, dimension: int, gpu: GpuRunner) -> None:
        super().__init__(model_name, "embedding", gpu)
        self.model_name = model_name
        self.dimension = dimension

    def _open(self) -> "SentenceTransformer":
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            self._name, device="cuda", local_files_only=True, model_kwargs={"dtype": _cuda_dtype(self._name)}
        )
        actual = model.get_embedding_dimension()
        if actual != self.dimension:
            raise _LoadRefused(
                f"The embedding model {self._name} makes {actual}-dimension vectors, but embedding_dimension is "
                f"{self.dimension}; set embedding_dimension = {actual} (with a new data_dir if Videos are already "
                "embedded)"
            )
        return model

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = self._call(
            lambda model: model.encode_document(list(texts), normalize_embeddings=True).astype("float32").tolist()
        )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vector: list[float] = self._call(
            lambda model: model.encode_query(text, normalize_embeddings=True).astype("float32").tolist()
        )
        return vector


class CrossEncoderReranker(_HubModel["CrossEncoder"]):
    """Scores are raw logits, as the Reranker port requires."""

    def __init__(self, model_name: str, gpu: GpuRunner) -> None:
        super().__init__(model_name, "reranking", gpu)

    def _open(self) -> "CrossEncoder":
        import torch
        from sentence_transformers import CrossEncoder

        # A single-label CrossEncoder applies a sigmoid by default; Identity keeps the logits.
        model: CrossEncoder = CrossEncoder(
            self._name,
            device="cuda",
            local_files_only=True,
            model_kwargs={"dtype": _cuda_dtype(self._name)},
            activation_fn=torch.nn.Identity(),
        )
        return model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        scores: list[float] = self._call(
            lambda model: model.predict([(query, p) for p in passages]).astype("float32").tolist()
        )
        return scores
