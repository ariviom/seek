# 02 — Run inference on CUDA, MPS or CPU and preserve search on reranker failure

**What to build:** A friend can ingest and search with the hardware available, see the actual devices and precision,
and still search if reranking fails. Drew's existing CUDA behaviour and stored vectors remain compatible.
(Stories 6–7, 9–13.)

**Blocked by:** 01 — Freeze real retrieval questions and record the CUDA baseline.

**Status:** in-progress — implementation and device verification in this session.

- [ ] Choose CUDA, then MPS, then CPU through a pure function of an injected probe result. Pass the selection to both
  model adapters, including standalone CLI Sync/reindex wiring as well as the server. No CUDA-only refusal remains.
- [ ] Use bfloat16 on supported CUDA devices and float32 otherwise, including MPS and CPU. Keep the embedding model,
  dimension, normalization, query/document prompts and existing CUDA ranking behaviour; keep the base-v2 reranker.
- [ ] Warm up the reranker with an actual scoring call before reporting it ready. An MPS load or scoring failure
  moves only the reranker to CPU and retries; the embedder remains on its selected device.
- [ ] Also handle the first scoring failure after a successful warm-up: make the reranker's one-time CPU fallback
  observable, retry the affected request, and avoid repeated device-switch attempts on subsequent searches.
- [ ] If the reranker is unavailable or fails on CPU too, return fused search results through the HTTP and MCP
  surfaces instead of failing the request. Preserve scope, Citation metadata, limits and Video diversity; expose
  the degraded model state rather than presenting it as successful reranking.
- [ ] Keep CUDA out-of-memory recovery CUDA-specific. MPS/CPU allocation failures become ordinary model failures,
  and no path invokes CUDA cleanup for a non-CUDA model. Preserve per-Video CUDA OOM handling during ingestion.
- [ ] Health and model events report each model's actual device, precision, fallback reason and failed state. Update
  the CLI status readout and affected types so a friend can identify the device before the later settings screen.
  These are additive model fields; the chat-health rename belongs to ticket 06.
- [ ] Preserve first-download progress and total bytes in existing terminal/web surfaces. With models completely
  cached, startup and local search work without a network connection. Missing cache content produces an actionable
  state. Offline support does not promise provider chat or YouTube ingestion without connectivity.
- [ ] On an Apple Silicon Mac in this ticket's session, load both real models, embed a passage and query, and score
  passages. Record actual MPS use or the reranker's CPU fallback, precision, outcome and hardware. Exercise CPU
  operation as well; a simulated probe alone does not verify execution.
- [ ] Re-run the unchanged CUDA regression set to catch unintended changes to Drew's path. Keep the snapshot and
  expected Videos intact; ticket 03 owns the separate MPS comparison on that snapshot.

**Verification:** Pure device/precision cases; HTTP search and model-status checks for load failure, first-call
failure and failed CPU retry; existing opt-in real-model checks extended to the selected device. Use injected model
execution failures where required to cover the wrapper fallback itself. Record the actual Mac and CUDA results.

**Closure precondition:** Mac access. Do not close solely on Linux unit tests.
