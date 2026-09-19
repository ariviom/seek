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

`mentor status`, `/api/health`, model events and the existing Server health dialog report
actual device, precision and fallback reason. Events continue after startup to expose runtime
changes. Download progress and byte totals remain visible. CUDA allocation cleanup and
per-Video embedding OOM recovery remain CUDA-specific.

## Real Apple Silicon and CPU checks

On the Mac, use this branch's checkout with `uv sync --frozen`. The first run may download
models. Execute only the device test, which uses production adapters without a database or
Sync worker:

```sh
MENTOR_DEVICE_RESULTS=/tmp/mentor-mac-auto.json \
uv run pytest -q -s -m real_models tests/test_real_devices.py

MENTOR_VERIFY_DEVICE=cpu MENTOR_DEVICE_RESULTS=/tmp/mentor-mac-cpu.json \
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
MENTOR_RETRIEVAL_SNAPSHOT=/home/drew/.local/share/mentor-baselines/build-0/retrieval.db \
MENTOR_RETRIEVAL_RESULTS=/tmp/mentor-ticket-02-cuda.json \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
uv run pytest -q -s -m real_models tests/test_retrieval_baseline.py
```

This ticket reruns CUDA only. Ticket 03 owns the separate real-corpus MPS comparison;
neither expected Videos nor the frozen corpus may be regenerated.

## Execution record

Actual hardware results and independent review are recorded here after verification.
Mac execution is required before ticket 02 can be marked complete.
