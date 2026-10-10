# Inference device verification

Ticket 02 keeps the embedding model, dimensions, prompts, normalization and base-v2 reranker.
Device selection is CUDA, then MPS, then CPU. CUDA uses bfloat16 where supported; all other
cases use float32. The server and standalone Sync/reindex pass the same selection policy
to the production adapters.

The reranker scores a warm-up passage before reporting ready. An MPS load or scoring failure
switches only the reranker to CPU once and retries. A later CPU failure is observable as a
failed model. Search then returns fused results with their existing citations, scope, limit
and Video diversity. Their score is zero (unscored), and reranker-dependent recency adjustment
is not applied. Successful reranked search is unchanged.

`seek status`, `/api/health`, model events and the existing Server health dialog report
actual device, precision and fallback reason. Events continue after startup to expose runtime
changes. Download progress and byte totals remain visible. CUDA allocation cleanup and
per-Video embedding OOM recovery remain CUDA-specific.

## Real Apple Silicon and CPU checks

On the Mac, use this branch's checkout with `uv sync --frozen`. The first run may download
models. Execute only the device test, which uses production adapters without a database or
Sync worker:

```sh
SEEK_DEVICE_RESULTS=/tmp/seek-mac-auto.json \
uv run pytest -q -s -m real_models tests/test_real_devices.py

SEEK_VERIFY_DEVICE=cpu SEEK_DEVICE_RESULTS=/tmp/seek-mac-cpu.json \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
uv run pytest -q -s -m real_models tests/test_real_devices.py
```

The first report must show Apple Silicon/MPS for the embedder, MPS or an explained CPU
fallback for the reranker, and float32. Both runs embed real passages and a query, check
finite normalized vectors and dimensions, and score relevant versus irrelevant passages.
The reports contain hardware, probe, actual model statuses, precision, versions, model
revisions, source revision and outcomes. Keep both JSON reports as execution evidence.

To check fully cached MPS operation offline, repeat the first command with
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`. Provider chat and YouTube Sync are outside this
offline promise. Missing cache content must report an actionable failure.

## CUDA regression

Use the unchanged ticket-01 snapshot, questions and manifest, following the service-stop
and restoration procedure in [retrieval-baseline.md](retrieval-baseline.md):

```sh
SEEK_RETRIEVAL_SNAPSHOT=/home/drew/.local/share/mentor-baselines/build-0/retrieval.db \
SEEK_RETRIEVAL_RESULTS=/tmp/mentor-ticket-02-cuda.json \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
uv run pytest -q -s -m real_models tests/test_retrieval_baseline.py
```

This ticket reruns CUDA only. Ticket 03 owns the separate real-corpus MPS comparison;
neither expected Videos nor the frozen corpus may be regenerated.

## Execution record

**Mac verification is explicitly deferred by Drew (2026-09-19): no Apple Silicon machine is available.**
The reviewed implementation and Linux checks are accepted for landing. Ticket 03's comparison
is parked; continue with ticket 04. The commands above remain the reopening procedure when
hardware becomes available. MPS support has not been verified on a real Mac.

Linux execution on clean `b7b39adbd78967c3f8e34a9db5f1a6b1d40e3626`, 2026-09-19:

- CUDA regression, 10:48:07–10:48:19 UTC: **10/10 questions pass** on RTX 3090, CUDA 13.0,
  bfloat16. The fixture and snapshot checksums match ticket 01. Full rankings and source
  hashes: [ticket-02-cuda.json](baselines/ticket-02-cuda.json).
- Real CPU execution, 10:48:23–10:48:28 UTC: **pass** on AMD Ryzen 7 5800X, float32,
  four torch threads. Two passage vectors and one query vector each have 1024 dimensions,
  finite values and norm approximately one. Relevant/irrelevant logits were 9.87257 and
  -5.34743. Both models are ready on CPU, with fully cached offline execution. Full report:
  [ticket-02-cpu.json](baselines/ticket-02-cpu.json). The CPU name was recorded using `lscpu`
  because Python's `platform.processor()` returned an empty string.
- Mentor was stopped around these runs with an EXIT trap to restore its prior active state.
  GPU memory was checked before CUDA loading; no unrelated workloads were evicted. After
  restoration the installed service was active and both models ready. The service remains
  on its prior installed code; this branch was not installed into the live service.
- `uv run pytest -q`: **366 passed, 4 opt-in tests deselected**. `uv run mypy`: 77 files
  pass. Web typecheck and build pass; the served bundle was rebuilt. Existing Playwright
  smoke passed. Focused health display checks passed at desktop, mobile and 200% zoom.
- Independent whole-branch Standards review: no hard violations, one optional duplication
  observation in test setup retained for local readability. Spec review: no implementation
  findings; real Mac execution remains the closure requirement.

The CPU command used was:

```sh
SEEK_VERIFY_DEVICE=cpu SEEK_DEVICE_RESULTS=/tmp/mentor-ticket-02-cpu.json \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
uv run pytest -q -s -m real_models tests/test_real_devices.py
```

For Mac verification without a published branch, transfer the prepared Git bundle
`/tmp/mentor-ticket-02.bundle` to the Mac and clone it into a new directory:

```sh
git clone --branch build-0/ticket-02-inference-devices ~/Downloads/mentor-ticket-02.bundle ~/mentor-ticket-02
cd ~/mentor-ticket-02
uv sync --frozen
```

When hardware is available, use current main (the bundle is an earlier implementation handoff),
run the Mac commands above and retain both JSON reports. No database snapshot or personal
configuration is needed for this ticket's Mac device test. Resolve failures here and review any
fixes. The full-corpus MPS comparison belongs to the deferred ticket 03.
