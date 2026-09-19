# 01 — Freeze real retrieval questions and record the CUDA baseline

**What to build:** An opt-in regression check that asks roughly ten real questions across Drew's existing Groups
and verifies the Videos that must appear, before the inference device implementation changes. (Story 14.)

**Blocked by:** None — can start once the shared implementation prerequisites are resolved; run this ticket first.

**Status:** done — 2026-09-18. Real CUDA run: 10/10 questions pass.

- [x] Questions, Group scope, required YouTube Video identifiers, result limit and recency preference live in a
  fixture file, not test code. Choose and verify the required Videos against the real content before the device
  change; record an explicit pass condition for each question.
- [x] Take one consistent frozen snapshot of the populated database, including all committed SQLite WAL contents.
  Keep the populated database outside git. Record its checksum, schema version, embedding model/dimension and model
  revisions with the results so another machine can identify the exact same inputs.
- [x] Locate the snapshot through a documented environment variable. With that variable absent, skip the regression
  check explicitly. If it is present but invalid, fail with an actionable message rather than reporting a skip or pass.
- [x] Use the existing real-model marker but a separate fixture from the temporary fake-transcript test. Exercise the
  production retrieval path without starting a Sync worker that could resume work and change the candidate pool.
  If a writable working copy is needed, derive it from the frozen snapshot and leave the original untouched.
- [x] Freeze time-dependent retrieval inputs as well as data, so elapsed time between CUDA and MPS runs cannot change
  recency ordering. Record the reference date and retrieval settings in the baseline manifest.
- [x] Stop Mentor for the CUDA run and check available GPU memory before loading both models. Restore its prior
  running state afterward. Do not evict unrelated workloads to make the run fit.
- [x] Run on the unchanged CUDA implementation and record actual ranked Video identifiers, pass/fail per question,
  hardware, precision, dependency versions and the source revision. Resolve baseline failures before closing.
- [x] Document the exact repeat command and snapshot-transfer requirements for the MPS run. Do not re-Sync,
  re-embed, regenerate expected Videos or replace the snapshot between baseline and comparison.
- [x] Explain the measurement's boundary: existing CUDA passage vectors are reused; this compares query embedding
  and reranking, not cross-device passage embedding. It is a retrieval regression, not a chat-model evaluation.

**Verification:** The recorded CUDA run is required evidence. Confirm the default test suite skips this opt-in
fixture when no snapshot is configured. A passing fake-transcript test alone cannot close this ticket.

## Closure evidence

- Implementation and exact CUDA run source: `673849dfe42b2dd0b197689914b6798c258991cd`.
- Real CUDA: 10/10 required Videos retrieved, RTX 3090, bfloat16, 2026-09-18 23:02 UTC.
  Full rankings and metadata: `docs/baselines/build-0-cuda.json`; repeat/transfer instructions:
  `docs/retrieval-baseline.md`. No inference or ranking source changed.
- Snapshot: `/home/drew/.local/share/mentor-baselines/build-0/retrieval.db`, external to git,
  read-only, SHA-256 `5504c1b1e96d4a11a7e229be6d3c24d9201e598e8d8fcbe724792f56d524c7da`.
  Checksum unchanged after execution. SQLite backup includes committed WAL.
- Scope correction explicitly approved by Drew: live database had no Groups; create the two
  fixture Groups only in a preparation copy. Live library still has zero Groups.
- Mentor stopped for execution; 21,590 MiB GPU memory free before model load. Prior active
  state restored through an EXIT trap; both models confirmed ready afterward.
- `uv run pytest -q`: 344 passed, 3 opt-in tests deselected. Explicit no-snapshot selection:
  1 skipped with the environment-variable instruction. Configured nonexistent path: 1 failed
  with actionable path error. Configuration tests cover corrupt/checksum/schema/model errors
  and working-copy isolation; snapshot command test covers committed WAL and overwrite refusal.
- `uv run mypy`: 72 source files pass. `pnpm --dir web run typecheck`: pass.
- Independent whole-branch Standards and Spec reviews: zero findings on both axes;
  final evidence review recorded in `.scratch/mentor-build-0/ticket-01-review.md`.
