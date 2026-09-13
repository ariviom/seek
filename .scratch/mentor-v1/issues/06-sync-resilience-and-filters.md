# 06 — Sync resilience and filters

**What to build:** An interrupted Sync picks up where it stopped when rerun. "Retry failed" per Channel recovers failures in one click. Rerunning a Sync processes only new Videos. Per-Channel filters (published after/before, playlist, most recent N) scope a large Channel. (Stories 11, 14, 15, 16.)

**Blocked by:** 05 — Sync: segmentation and embedding

**Status:** done

- [x] Interrupting a Sync by raising from a fake mid-run, then rerunning, completes only the unfinished Videos (asserted via fake call counts)
- [x] A normal Sync skips permanently failed Videos and retries transient failures; "retry failed" resets all failed Videos to their `failure_stage`
- [x] A rerun Sync does no transcript or embed work for Videos already `done`
- [x] Filters are editable per Channel via API and UI; every Sync re-applies the current filters, so widening a filter makes older Videos eligible and narrowing one marks them `excluded`
- [x] API tests cover each story

From ticket 01 review: VideoListing has no publish date and there is no playlist listing; both are needed to apply filters at discovery.

From ticket 02 review: PATCH /api/channels/{id} currently requires `indexed`; make fields optional when adding filters.

From ticket 04 review: `failure_stage` holds the stage attempted, and `pipeline_stage` still holds the last completed stage. So "retry failed" means clearing the failure columns, not setting `pipeline_stage` to `failure_stage`. Transient retry on a normal Sync already exists and is tested; add the filter exclusions into `videos.record_discovery` next to the duration rule.

From ticket 05 review:
- `tests/test_segments.py` fakes a retry by writing `videos.pipeline_stage` directly; switch it to the retry API once it exists.
- Excluded Videos keep their Segments and vectors, and vec0 only has `channel_id` metadata, so excluded Segments would take KNN top-k slots in ticket 09. Decide here: delete an excluded Video's Segments (and set `pipeline_stage` back to `transcript_fetched`, so lifting the exclusion re-segments without refetching), or add a scoping column via a new vec0 table.
- `videos.complete_stage` clears failure columns; route any new stage transitions through it.
- `SyncWorker._advance` refreshes Sync stage counts after every stage (4 GROUP BY scans per Video). Fine at expected volume; revisit if ticket 07's SSE wants something cheaper.

Done note: filters live on `channels` (`published_after`/`published_before` inclusive, `playlist_id`, `most_recent`). `PATCH /api/channels/{id}` takes optional `indexed` and an optional `filters` object replaced as a whole (null or omitted = unchanged). A Sync snapshots the filters when claimed (`ClaimedSync.filters`); edits apply from the next Sync. Discovery lists the playlist (port method `list_playlist`; `PlaylistNotFound` fails the Sync) and the videos tab, upserts, then `videos._apply_exclusions` recomputes every Video's exclusion in order: too short, outside the date range (listing date, or the stored date from details), not in the playlist, beyond the N newest eligible (by listing position; Videos missing from a short listing follow by publish date). Duration and date are re-checked when details arrive; such a Video keeps its Transcript at `transcript_fetched`, and with `most_recent` set the Sync re-applies exclusions and processes Videos that became eligible. Decision on the ticket 05 question: an excluded Video's Segments (and so its FTS5 and vec0 rows) are deleted and it steps back to `transcript_fetched` through `complete_stage`, so lifting the exclusion re-segments without refetching. `POST /api/channels/{id}/retry-failed` clears failures at once and queues a Sync with `retry_failed = 1`, which clears them again when claimed, catching failures recorded by a Sync still running.

From ticket 06 review (deferred):
- `tests/test_segments.py` still writes `videos.pipeline_stage` directly. Not switched: no API path re-runs a stage for a Video that still has Segments or vectors (retry resumes after the last completed stage; exclusion deletes Segments first), so that is the only way to reach the replace logic in `segments.record_segments` and `record_embeddings`.
- `most_recent` counts failed Videos (members-only, non-English) among the N. Needs a product decision: "N most recent" (current) or "N indexable". Decided during ticket 08 (2026-09-13): keep "N most recent". The window is then what the Channel shows, it doesn't shift as Videos fail or retries succeed, and a Channel full of members-only Videos can't send a Sync fetching down its whole back catalogue.
- With undated listings and a date filter, a Sync fetches Videos down the listing until N are in range. Ticket 08 should supply listing dates where yt-dlp can.
- Databases from before ticket 06 keep Segments for Videos excluded while `done` until their Channel's next Sync. No real data exists yet.
- Small cleanups not done: `_require_channel` exists in both `syncs.py` and `videos.py`; `FailsOn` (test_sync_resilience) and `BrokenOnGarbledText` (test_segments) are the same fake shape; the 422 for a bad playlist id is pydantic's pattern text; "Retry failed" is always enabled.
