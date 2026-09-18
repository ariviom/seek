# 03 — Compare MPS retrieval against the frozen CUDA baseline

**What to build:** Evidence that a friend's Apple Silicon retrieval still returns the required Videos for the real
questions recorded before the device change. (Story 14.)

**Blocked by:** 02 — Run inference on CUDA, MPS or CPU and preserve search on reranker failure.

**Status:** ready-for-agent

- [ ] Transfer the exact frozen snapshot and fixture from ticket 01 to an Apple Silicon Mac. Verify the checksum,
  schema, model revisions, reference date, retrieval settings and required Video identifiers before comparing.
- [ ] Run the regression set through the production retrieval path with MPS query embedding. Record the reranker's
  actual device: MPS if supported, CPU if the implemented fallback is needed. Label the result accurately.
- [ ] Record ranked Videos and pass/fail for each question beside the CUDA baseline. Every predeclared required-Video
  condition must pass; do not silently accept missing Videos because numeric scores differ across kernels.
- [ ] Investigate and fix implementation-induced regressions before closing. Re-run the affected comparison and
  CUDA checks after a fix. A change to the corpus or expected answers requires an explicitly reviewed new baseline,
  not an edit that makes this run green.
- [ ] Preserve the original snapshot and avoid all Sync/reindex work during the comparison. If an environment
  mismatch prevents a meaningful comparison, record it as a blocker rather than a successful hardware check.
- [ ] Store a compact reproducible report with source revision, dependency versions, hardware, devices, precision,
  fallback reasons, snapshot identity and the exact run command. No populated user database is committed.
- [ ] State that stored passage embeddings are CUDA-produced and unchanged. The evidence establishes query/rerank
  compatibility for this corpus; it does not claim passage-embedding equivalence or universal ranking equivalence.

**Verification:** The real same-snapshot MPS run and its comparison report are this ticket's deliverable. Ticket 02's
small real-model smoke test cannot substitute for it.

**Closure precondition:** Mac access and the baseline artifacts from ticket 01.
