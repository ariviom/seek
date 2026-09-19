# 02 — Run inference on CUDA, MPS or CPU and preserve search on reranker failure

**What to build:** A friend can ingest and search with the hardware available, see the actual devices and precision,
and still search if reranking fails. Drew's existing CUDA behaviour and stored vectors remain compatible.
(Stories 6–7, 9–13.)

**Blocked by:** 01 — Freeze real retrieval questions and record the CUDA baseline.

**Status:** implemented and accepted for landing — Mac verification explicitly deferred by Drew on 2026-09-19.
The unchecked Mac criterion remains unverified; Linux CPU/CUDA evidence is recorded below.

- [x] Choose CUDA, then MPS, then CPU through a pure function of an injected probe result. Pass the selection to both
  model adapters, including standalone CLI Sync/reindex wiring as well as the server. No CUDA-only refusal remains.
- [x] Use bfloat16 on supported CUDA devices and float32 otherwise, including MPS and CPU. Keep the embedding model,
  dimension, normalization, query/document prompts and existing CUDA ranking behaviour; keep the base-v2 reranker.
- [x] Warm up the reranker with an actual scoring call before reporting it ready. An MPS load or scoring failure
  moves only the reranker to CPU and retries; the embedder remains on its selected device.
- [x] Also handle the first scoring failure after a successful warm-up: make the reranker's one-time CPU fallback
  observable, retry the affected request, and avoid repeated device-switch attempts on subsequent searches.
- [x] If the reranker is unavailable or fails on CPU too, return fused search results through the HTTP and MCP
  surfaces instead of failing the request. Preserve scope, Citation metadata, limits and Video diversity; expose
  the degraded model state rather than presenting it as successful reranking.
- [x] Keep CUDA out-of-memory recovery CUDA-specific. MPS/CPU allocation failures become ordinary model failures,
  and no path invokes CUDA cleanup for a non-CUDA model. Preserve per-Video CUDA OOM handling during ingestion.
- [x] Health and model events report each model's actual device, precision, fallback reason and failed state. Update
  the CLI status readout and affected types so a friend can identify the device before the later settings screen.
  These are additive model fields; the chat-health rename belongs to ticket 06.
- [x] Preserve first-download progress and total bytes in existing terminal/web surfaces. With models completely
  cached, startup and local search work without a network connection. Missing cache content produces an actionable
  state. Offline support does not promise provider chat or YouTube ingestion without connectivity.
- [ ] On an Apple Silicon Mac in this ticket's session, load both real models, embed a passage and query, and score
  passages. Record actual MPS use or the reranker's CPU fallback, precision, outcome and hardware. Exercise CPU
  operation as well; a simulated probe alone does not verify execution.
- [x] Re-run the unchanged CUDA regression set to catch unintended changes to Drew's path. Keep the snapshot and
  expected Videos intact; ticket 03 owns the separate MPS comparison on that snapshot.

**Verification:** Pure device/precision cases; HTTP search and model-status checks for load failure, first-call
failure and failed CPU retry; existing opt-in real-model checks extended to the selected device. Use injected model
execution failures where required to cover the wrapper fallback itself. Record the actual Mac and CUDA results.

**Revised closure decision (Drew, 2026-09-19):** no Apple Silicon machine is available. Defer the real Mac
checks and land the reviewed implementation with its Linux CPU/CUDA evidence. Reopen the unchecked Mac
criterion when hardware becomes available; do not claim MPS execution verified.

## Progress — 2026-09-19

Implementation: `b7b39adbd78967c3f8e34a9db5f1a6b1d40e3626` on
`build-0/ticket-02-inference-devices`, worktree `/home/drew/mentor-ticket-02`.
All implementation criteria and Linux verification are addressed; the Mac execution box
remains open. Details, exact commands and reports: `docs/inference-devices.md`.

- CUDA regression: 10/10 on the unchanged snapshot/fixture, actual CUDA/bfloat16, snapshot unchanged.
- Real Linux CPU embedding and reranking: pass, float32, offline with complete model caches.
- Ordinary tests: 366 passed, 4 deselected; mypy 77 files, web typecheck/build and Playwright smoke pass.
- Actual-wrapper failure injection checked through HTTP search and health, in addition to
  model-port tests, generic HTTP/MCP fallback, model events, CLI status and device selection tests.
- Independent whole-branch reviews: no hard Standards violations or implementation Spec findings.
  An optional duplicated test-fake observation was retained for explicit, independent seam setup.
- Mentor's previous active service state restored, both installed models ready. No live reinstall.
- Mac execution remains deferred under Drew's revised decision above. Ticket 03 is parked for the same
  hardware limitation. Proceed with ticket 04; preserve the prepared verification commands and frozen corpus.
