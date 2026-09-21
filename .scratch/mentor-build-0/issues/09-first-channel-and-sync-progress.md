# 09 — Guide a first Channel and show an honest Sync rate and estimate

**What to build:** A friend is encouraged to start small while adding a Channel and can see a running Sync's rate,
estimated finish and per-Video failures, with progress that survives a reload and interrupted work that resumes.
(Stories 31–32, 34–35.)

**Blocked by:** None — can start once the shared implementation prerequisites are resolved.

**Status:** complete — 511 tests passing (browser smoke included), mypy and web typecheck clean, served bundle
rebuilt. A Sync's completed, failed and remaining counts are derived per Video, so work redone after a restart,
retry or reindex is counted once.

- [x] Add concise start-with-a-small-Channel advice at the moment of adding one, explaining that a large catalogue
  takes time. Do not perform a paced listing to promise a pre-ingestion Video count.
- [x] Reuse the existing persisted Sync progress and live updates. Display an explicit observed processing rate
  alongside approximate time remaining, with clear units and a warm-up state until enough observations exist.
- [x] Distinguish Videos processed from Videos ready to answer: a failed Video counts as completed work but not as
  a searchable success. Retry-failed runs account for their remaining failed Videos, avoiding impossible totals.
- [x] Keep Library/Channel/Sync views consistent about the running Sync, counts and failure state. Reload preserves
  progress; no rate or ETA is fabricated while queued, during discovery without a useful total, or after failure.
- [x] On process restart, use compatible count/time baselines for rate and ETA. The current lease recovery resets
  `started_at` while retaining `completed_videos`; never divide retained pre-restart work by fresh elapsed time.
  Preserve a compatible interval or warm up a new observed interval without erasing total completion progress.
- [x] Verify foreground shutdown/restart resumes persisted unfinished stages without discarding completed work.
  Preserve ordinary per-Video failure isolation and existing deliberate whole-Sync behaviour for source-wide
  throttling or other shared failures; "one Video failed" must not imply every source failure is ignored.
- [x] Keep per-Video failure reasons and existing retry actions discoverable. A friend can leave ingestion running
  without holding the browser tab open.
- [x] Scope fixes to these spec requirements. Existing unrelated v2 polish findings are not silently folded into
  this ticket; v2 ticket 06 is explicitly parked, with friend-workflow blockers addressed by their owning criteria.

**Verification:** Reuse/extend API and event-stream tests for progress, per-Video failure and restart recovery, and
the served UI smoke for add-Channel advice and visible Sync progress. Exercise a failure and retry-failed case plus a
reload while work is held by the existing harness. Restart after several completed Videos and assert that total
progress survives while rate/ETA either use a compatible interval or return to warm-up. Do not rebuild the
already-working Sync pipeline.
