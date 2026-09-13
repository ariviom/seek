# 10 — Real models

**What to build:** Search runs on the real embedding and reranker models on the GPU. Models download on first use with visible progress, and the tool stays understandable while they load. (Story 49.)

**Blocked by:** 09 — Hybrid search

**Status:** done

- [x] sentence-transformers Embedder (query instruction prompt, passages unprefixed) and Reranker on CUDA; model names and fallbacks come from config
- [x] Confirm the configured reranker loads through sentence-transformers; if it does not, use the documented fallback and note it
- [x] Models preload in the background at startup; Health shows download/load progress; search and sync return a clear "models loading" error until ready
- [x] GPU out-of-memory surfaces as a clear error (Sync failure reason or search error), not a crash
- [x] Opt-in `real_models` test (skipped by default) ranks a planted Segment first for a known query

From ticket 01 review: GPU work needs its own single-thread executor rather than the default thread pool; take the embedding dimension from config so the startup mismatch check does not wait for model load.

From ticket 05 review:
- The Embedder port promises `model_name` and `dimension` before loading; the stub `embeddings.SentenceTransformerEmbedder` takes them from config. If the adapter falls back to another model, it must report the fallback's name and dimension (and the startup check must see them), or refuse rather than silently store vectors under the primary's stamp. Nothing ties `embedding_dimension` to the model: validate it on load and raise a clear `ModelUnavailable`.
- Map GPU OOM to `ModelUnavailable` so it stops the Sync; other embedder exceptions currently fail one Video transiently.
- Startup refusals (model mismatch, newer schema) raise `RuntimeError` inside the lifespan, which uvicorn prints as a traceback. Consider surfacing them as a one-line `mentor: ...` exit like config errors.

From ticket 09 review:
- The Reranker port returns raw logits and `ranking.recency_score` applies the sigmoid. sentence-transformers' CrossEncoder may default to a sigmoid activation for one-label models; make sure the adapter returns logits, or scores collapse into 0.5–0.73 and recency dominates. The default half-lives (gentle 3650 days, strong 1095) were chosen against the fake's 0–1 scores; check them against real logits on a planted near-tie.
- `embeddings.SentenceTransformerReranker` takes no arguments; build it from reranker model config like the embedder. `search.Search` calls `embed_query` and `score` through `asyncio.to_thread`; move both to the GPU executor.

Done note: `models.py` (replacing `embeddings.py`) has `SentenceTransformerEmbedder` (Qwen/Qwen3-Embedding-0.6B: `encode_query` adds its query instruction, `encode_document` its empty document prompt; normalised) and `CrossEncoderReranker` (mixedbread-ai/mxbai-rerank-base-v2, which loads natively through sentence-transformers 6.0.1's CrossEncoder; `activation_fn=Identity` keeps raw logits). Both run in bfloat16 on CUDA and fail with a clear message without a GPU. Every model call runs on one `GpuRunner` thread. Config: `embedding_model`, `embedding_dimension`, `reranker_model`. **No automatic fallback**: a fallback is used by configuring its name (bge-reranker-v2-m3 loads the same way; the documented embedding fallback, Snowflake arctic-embed-m-v2.0, needs remote code, which isn't enabled). The port gained `load()` (never raises) and `status()` (`ModelStatus`: waiting, downloading with bytes, loading, ready, failed with a message). The lifespan loads the models in order on a daemon thread, publishes `models` events on every status change, and Health reports them; the web UI shows a header notice and footer entries. Downloads go through `snapshot_download` (skipping ONNX/OpenVINO/TF/Flax files), whose byte progress feeds the status; a complete cache works offline. Calls before a model is ready raise ModelUnavailable ("still loading", "downloading N of M MB", or the failure). **Syncs wait** while the embedding model loads instead of failing; if it failed, a Sync fails at once with its reason, before any YouTube calls. OOM while loading or running maps to a message saying to free GPU memory; a wrong embedding dimension or unknown repository fails loading with a message. Measured: both models hold about 2.1 GB of VRAM; a 32-passage batch peaks near 3.3 GB. `uv run pytest -m real_models` passes.

Review fixes (both axes), including a design change agreed with Drew: on real logits the sigmoid saturated (relevant ≈0.9999) and recency outranked relevance, so a result now scores `sigmoid(logit / reranker_temperature) × (1 − max_penalty × (1 − 0.5^(age / half_life)))` with temperature 3 and max penalties gentle 15% / strong 50% (see the spec's implementation amendments); the real-models test checks that a newer copy wins a tie and a new irrelevant Video doesn't beat an old relevant one under strong. Also: `load()` could raise if torch failed to import and leave "loading" forever; fp16 → bf16; progress now counts bytes written so it reaches its total; no "downloading" flash when offline; gated repos get their own message; the worker takes the lease before waiting (so stale running Syncs are reconciled) and is woken only on state changes; the fakes raise until loaded like the real adapters; a UI race let an in-flight Health response undo a newer `models` event.

From ticket 10 review (deferred):
- Callers still wrap blocking model calls in `asyncio.to_thread`, so each queued search or embed parks a default-pool thread (shared with `Database.run`) while waiting on the GPU thread; `asyncio.wrap_future` over the GPU executor would free them.
- A failed load is never retried; a first start without network needs a restart once online.
- Startup refusals (model mismatch, newer schema) still print a traceback rather than a one-line `mentor: ...` exit.
- Stopping the server while a model is moving onto the GPU waits for that (about a second); stopping after a download finished but before loading can log "cannot schedule new futures after interpreter shutdown".
- CUDA allocation failures that arrive as a plain `RuntimeError` (e.g. `CUBLAS_STATUS_ALLOC_FAILED`) get the generic message and fail one Video transiently rather than stopping the Sync.
- tqdm prints download bars to stderr, which lands in the journal under systemd.
