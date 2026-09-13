# 06 — Sync resilience and filters

**What to build:** An interrupted Sync picks up where it stopped when rerun. "Retry failed" per Channel recovers failures in one click. Rerunning a Sync processes only new Videos. Per-Channel filters (published after/before, playlist, most recent N) scope a large Channel. (Stories 11, 14, 15, 16.)

**Blocked by:** 05 — Sync: segmentation and embedding

**Status:** ready-for-agent

- [ ] Interrupting a Sync by raising from a fake mid-run, then rerunning, completes only the unfinished Videos (asserted via fake call counts)
- [ ] A normal Sync skips permanently failed Videos and retries transient failures; "retry failed" resets all failed Videos to their `failure_stage`
- [ ] A rerun Sync does no transcript or embed work for Videos already `done`
- [ ] Filters are editable per Channel via API and UI; every Sync re-applies the current filters, so widening a filter makes older Videos eligible and narrowing one marks them `excluded`
- [ ] API tests cover each story

From ticket 01 review: VideoListing has no publish date and there is no playlist listing; both are needed to apply filters at discovery.

From ticket 02 review: PATCH /api/channels/{id} currently requires `indexed`; make fields optional when adding filters.

From ticket 04 review: `failure_stage` holds the stage attempted, and `pipeline_stage` still holds the last completed stage. So "retry failed" means clearing the failure columns, not setting `pipeline_stage` to `failure_stage`. Transient retry on a normal Sync already exists and is tested; add the filter exclusions into `videos.record_discovery` next to the duration rule.

From ticket 05 review:
- `tests/test_segments.py` fakes a retry by writing `videos.pipeline_stage` directly; switch it to the retry API once it exists.
- Excluded Videos keep their Segments and vectors, and vec0 only has `channel_id` metadata, so excluded Segments would take KNN top-k slots in ticket 09. Decide here: delete an excluded Video's Segments (and set `pipeline_stage` back to `transcript_fetched`, so lifting the exclusion re-segments without refetching), or add a scoping column via a new vec0 table.
- `videos.complete_stage` clears failure columns; route any new stage transitions through it.
- `SyncWorker._advance` refreshes Sync stage counts after every stage (4 GROUP BY scans per Video). Fine at expected volume; revisit if ticket 07's SSE wants something cheaper.
