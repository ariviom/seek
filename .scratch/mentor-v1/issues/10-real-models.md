# 10 — Real models

**What to build:** Search runs on the real embedding and reranker models on the GPU. Models download on first use with visible progress, and the tool stays understandable while they load. (Story 49.)

**Blocked by:** 09 — Hybrid search

**Status:** ready-for-agent

- [ ] sentence-transformers Embedder (query instruction prompt, passages unprefixed) and Reranker on CUDA; model names and fallbacks come from config
- [ ] Confirm the configured reranker loads through sentence-transformers; if it does not, use the documented fallback and note it
- [ ] Models preload in the background at startup; Health shows download/load progress; search and sync return a clear "models loading" error until ready
- [ ] GPU out-of-memory surfaces as a clear error (Sync failure reason or search error), not a crash
- [ ] Opt-in `real_models` test (skipped by default) ranks a planted Segment first for a known query

From ticket 01 review: GPU work needs its own single-thread executor rather than the default thread pool; take the embedding dimension from config so the startup mismatch check does not wait for model load.

From ticket 05 review:
- The Embedder port promises `model_name` and `dimension` before loading; the stub `embeddings.SentenceTransformerEmbedder` takes them from config. If the adapter falls back to another model, it must report the fallback's name and dimension (and the startup check must see them), or refuse rather than silently store vectors under the primary's stamp. Nothing ties `embedding_dimension` to the model: validate it on load and raise a clear `ModelUnavailable`.
- Map GPU OOM to `ModelUnavailable` so it stops the Sync; other embedder exceptions currently fail one Video transiently.
- Startup refusals (model mismatch, newer schema) raise `RuntimeError` inside the lifespan, which uvicorn prints as a traceback. Consider surfacing them as a one-line `mentor: ...` exit like config errors.

From ticket 09 review:
- The Reranker port returns raw logits and `ranking.recency_score` applies the sigmoid. sentence-transformers' CrossEncoder may default to a sigmoid activation for one-label models; make sure the adapter returns logits, or scores collapse into 0.5–0.73 and recency dominates. The default half-lives (gentle 3650 days, strong 1095) were chosen against the fake's 0–1 scores; check them against real logits on a planted near-tie.
- `embeddings.SentenceTransformerReranker` takes no arguments; build it from reranker model config like the embedder. `search.Search` calls `embed_query` and `score` through `asyncio.to_thread`; move both to the GPU executor.
