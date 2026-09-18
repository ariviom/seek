# 01 — Freeze real retrieval questions and record the CUDA baseline

**What to build:** An opt-in regression check that asks roughly ten real questions across Drew's existing Groups
and verifies the Videos that must appear, before the inference device implementation changes. (Story 14.)

**Blocked by:** None — can start once the shared implementation prerequisites are resolved; run this ticket first.

**Status:** ready-for-agent

- [ ] Questions, Group scope, required YouTube Video identifiers, result limit and recency preference live in a
  fixture file, not test code. Choose and verify the required Videos against the real content before the device
  change; record an explicit pass condition for each question.
- [ ] Take one consistent frozen snapshot of the populated database, including all committed SQLite WAL contents.
  Keep the populated database outside git. Record its checksum, schema version, embedding model/dimension and model
  revisions with the results so another machine can identify the exact same inputs.
- [ ] Locate the snapshot through a documented environment variable. With that variable absent, skip the regression
  check explicitly. If it is present but invalid, fail with an actionable message rather than reporting a skip or pass.
- [ ] Use the existing real-model marker but a separate fixture from the temporary fake-transcript test. Exercise the
  production retrieval path without starting a Sync worker that could resume work and change the candidate pool.
  If a writable working copy is needed, derive it from the frozen snapshot and leave the original untouched.
- [ ] Freeze time-dependent retrieval inputs as well as data, so elapsed time between CUDA and MPS runs cannot change
  recency ordering. Record the reference date and retrieval settings in the baseline manifest.
- [ ] Stop Mentor for the CUDA run and check available GPU memory before loading both models. Restore its prior
  running state afterward. Do not evict unrelated workloads to make the run fit.
- [ ] Run on the unchanged CUDA implementation and record actual ranked Video identifiers, pass/fail per question,
  hardware, precision, dependency versions and the source revision. Resolve baseline failures before closing.
- [ ] Document the exact repeat command and snapshot-transfer requirements for the MPS run. Do not re-Sync,
  re-embed, regenerate expected Videos or replace the snapshot between baseline and comparison.
- [ ] Explain the measurement's boundary: existing CUDA passage vectors are reused; this compares query embedding
  and reranking, not cross-device passage embedding. It is a retrieval regression, not a chat-model evaluation.

**Verification:** The recorded CUDA run is required evidence. Confirm the default test suite skips this opt-in
fixture when no snapshot is configured. A passing fake-transcript test alone cannot close this ticket.
