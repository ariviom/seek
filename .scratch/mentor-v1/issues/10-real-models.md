# 10 — Real models

**What to build:** Search runs on the real embedding and reranker models on the GPU. Models download on first use with visible progress, and the tool stays understandable while they load. (Story 49.)

**Blocked by:** 09 — Hybrid search

**Status:** ready-for-agent

- [ ] sentence-transformers Embedder (query instruction prompt, passages unprefixed) and Reranker on CUDA; model names and fallbacks come from config
- [ ] Confirm the configured reranker loads through sentence-transformers; if it does not, use the documented fallback and note it
- [ ] Models preload in the background at startup; Health shows download/load progress; search and sync return a clear "models loading" error until ready
- [ ] GPU out-of-memory surfaces as a clear error (Sync failure reason or search error), not a crash
- [ ] Opt-in `real_models` test (skipped by default) ranks a planted Segment first for a known query
