"""The embedding and reranking models, run with sentence-transformers on the selected device.

Models download from Hugging Face on first use and are cached there. torch and sentence-transformers are imported only
when a model loads, so commands and tests that don't need them start quickly.
"""

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from tqdm.auto import tqdm

from seek.devices import DeviceSelection, probe_device, select_device
from seek.ports import GpuOutOfMemory, ModelStatus, ModelUnavailable

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
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="seek-gpu")

    def run[T](self, work: Callable[[], T]) -> T:
        return self._executor.submit(work).result()


class _LoadRefused(Exception):
    """The model can't be used as configured; the message is for the user."""


class _HubModel[M]:
    """A Hugging Face model that downloads and loads in load(), then runs its calls on the GPU thread."""

    def __init__(
        self, name: str, role: Literal["embedding", "reranking"], gpu: GpuRunner,
        selection: DeviceSelection | None = None,
    ) -> None:
        self._name = name
        self._role = role
        self._gpu = gpu
        self._selection = selection
        self._model: M | None = None
        # Replaced whole, never mutated, so readers on other threads see a consistent status.
        self._status = ModelStatus(
            name, "waiting", device=selection.device if selection else None,
            precision=selection.precision if selection else None,
        )

    def status(self) -> ModelStatus:
        return self._status

    def load(self) -> None:
        try:
            if self._selection is None:
                self._selection = select_device(probe_device())
            self._status = replace(
                self._status, device=self._selection.device, precision=self._selection.precision
            )
            self._download()
            self._status = replace(self._status, state="loading", downloaded_bytes=None, total_bytes=None, error=None)
            self._gpu.run(self._load_on_device)
        except Exception as error:
            self._fail(error, "load")

    def _load_on_device(self) -> None:
        try:
            self._model = self._open()
        except Exception as error:
            if not self._fallback(error):
                raise
        self._status = replace(self._status, state="ready", error=None)

    def _fallback(self, error: Exception) -> bool:
        # Only the cross-encoder needs the known MPS escape hatch. After switching, every future call sees CPU.
        if self._role != "reranking" or self._selection is None or self._selection.device != "mps":
            return False
        self._model = None
        self._selection = DeviceSelection("cpu", "float32")
        self._status = replace(
            self._status, state="loading", device="cpu", precision="float32",
            fallback_reason=f"MPS reranking failed; using CPU: {error}",
        )
        self._model = self._open()
        return True

    def _fail(self, error: Exception, operation: str) -> None:
        self._model = None
        try:
            message = self._expected_failure(error)
        except Exception:
            message = None
        if message is None:
            log.exception("Could not %s %s", operation, self._name)
            message = f"Could not {operation} the {self._role} model {self._name}: {error}"
        self._status = replace(self._status, state="failed", error=message)

    def _dtype(self) -> object:
        import torch

        assert self._selection is not None
        return torch.bfloat16 if self._selection.precision == "bfloat16" else torch.float32

    def _expected_failure(self, error: Exception) -> str | None:
        """A message for the user if this is a failure worth no traceback."""
        import torch
        from huggingface_hub.errors import GatedRepoError, LocalEntryNotFoundError, RepositoryNotFoundError

        if isinstance(error, _LoadRefused):
            return str(error)
        if self._selection is not None and self._selection.device == "cuda" and isinstance(error, torch.OutOfMemoryError):
            torch.cuda.empty_cache()
            return (
                f"The GPU ran out of memory loading the {self._role} model {self._name}; free GPU memory used by "
                "other programs and restart Seek"
            )
        if isinstance(error, GatedRepoError):
            return (
                f"The {self._role} model {self._name} is gated on Hugging Face; accept its terms and log in with "
                "`hf auth login`, then restart Seek"
            )
        if isinstance(error, RepositoryNotFoundError):
            return f"Hugging Face has no model named {self._name}; check the configured {self._role} model"
        if isinstance(error, LocalEntryNotFoundError):
            return (
                f"The {self._role} model {self._name} isn't downloaded yet and Hugging Face can't be reached; "
                "restart Seek once online"
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
            self._status = replace(self._status, state="downloading", downloaded_bytes=0, total_bytes=missing)
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
        self._status = replace(self._status, state="downloading", downloaded_bytes=min(downloaded, total), total_bytes=total)

    def _open(self) -> M:
        raise NotImplementedError

    def _call[T](self, work: Callable[[M], T]) -> T:
        def on_device() -> T:
            import torch

            # Resolve the model inside the serial executor: another call may just have moved it to CPU.
            model = self._model
            if model is None or self._status.state != "ready":
                raise ModelUnavailable(self._not_ready())
            try:
                return work(model)
            except Exception as error:
                if (self._selection is not None and self._selection.device == "cuda"
                        and isinstance(error, torch.OutOfMemoryError)):
                    torch.cuda.empty_cache()
                    message = (
                        f"The GPU ran out of memory running the {self._role} model {self._name}; free GPU memory used by "
                        "other programs and try again"
                    )
                    if self._role == "reranking":
                        self._model = None
                        self._status = replace(self._status, state="failed", error=message)
                    raise GpuOutOfMemory(message) from None
                try:
                    if self._fallback(error):
                        assert self._model is not None
                        result = work(self._model)
                        self._status = replace(self._status, state="ready", error=None)
                        return result
                except Exception as retry_error:
                    error = retry_error
                self._fail(error, "run")
                raise ModelUnavailable(self._not_ready()) from error

        return self._gpu.run(on_device)

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



class SentenceTransformerEmbedder(_HubModel["SentenceTransformer"]):
    """Queries carry the model's query prompt; passages get its document prompt, which the default model leaves
    empty. Vectors are L2-normalised."""

    def __init__(
        self, model_name: str, dimension: int, gpu: GpuRunner, selection: DeviceSelection | None = None
    ) -> None:
        super().__init__(model_name, "embedding", gpu, selection)
        self.model_name = model_name
        self.dimension = dimension

    def _open(self) -> "SentenceTransformer":
        from sentence_transformers import SentenceTransformer

        assert self._selection is not None
        model = SentenceTransformer(
            self._name, device=self._selection.device, local_files_only=True, model_kwargs={"dtype": self._dtype()}
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

    def __init__(
        self, model_name: str, gpu: GpuRunner, selection: DeviceSelection | None = None
    ) -> None:
        super().__init__(model_name, "reranking", gpu, selection)

    def _open(self) -> "CrossEncoder":
        import torch
        from sentence_transformers import CrossEncoder

        # A single-label CrossEncoder applies a sigmoid by default; Identity keeps the logits.
        assert self._selection is not None
        model: CrossEncoder = CrossEncoder(
            self._name,
            device=self._selection.device,
            local_files_only=True,
            model_kwargs={"dtype": self._dtype()},
            activation_fn=torch.nn.Identity(),
        )
        # Some MPS failures surface only in predict; readiness includes a real scoring operation.
        model.predict([("What is the topic?", "This passage explains the topic.")])
        return model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        scores: list[float] = self._call(
            lambda model: model.predict([(query, p) for p in passages]).astype("float32").tolist()
        )
        return scores
