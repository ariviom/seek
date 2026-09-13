# 04 — Sync: discovery and transcripts

**What to build:** Start a Sync for a Channel from the web UI. It discovers the Channel's Videos, excludes Shorts and too-short Videos, and fetches transcripts and full metadata. The Channel's Video list shows each Video's Pipeline stage and any exclusion or failure reason. Syncs are queued and run one at a time. (Stories 9, 10, 13, 17, 18, 19; uses fakes.)

**Blocked by:** 02 — Mentors and Channels

**Status:** done

- [x] Discovery is a cheap flat listing of the Channel's videos tab (Shorts are not on it), upserted by YouTube video id
- [x] Videos under the configurable minimum duration (default 120 s) get stage `excluded` with a reason; they are not failed and not processed
- [x] Transcript stage fetches English captions as timestamped cues plus full metadata (chapters, description, publish date); Transcript records source and language
- [x] Members-only, age-restricted, live/upcoming, caption-less, and non-English Videos become `failed` with reason, `failure_stage`, and a permanent/transient class; non-English records the language; the Sync continues
- [x] `pipeline_stage` records the last completed stage; each stage runs per Video in its own short transaction
- [x] Sync queue persists in the database, is FIFO, runs one Sync at a time, and dedupes a Channel already queued
- [x] A lease row prevents a second worker in any process; on startup, Syncs left "running" are reconciled
- [x] A Channel deleted mid-Sync is skipped without errors or orphan rows
- [x] Sync record holds per-stage counts and timestamps; Videos list API and UI table show stage, reason, metadata
- [x] API tests drive all of the above through FakeTranscriptSource

From ticket 01 review:
- Connections use autocommit; add a write-transaction helper using BEGIN IMMEDIATE (`with conn:` does not open a transaction).
- TranscriptSource needs a failure type carrying reason, permanent/transient, and language; decide whether metadata fetch is separate from caption fetch so a caption-less Video keeps its metadata.
- Pick one unknown-id behaviour for the port and make FakeTranscriptSource match; add call recording and per-video error injection.

Done note: `fetch_video` stays one call; `VideoUnavailable` carries `details` so a caption-less Video keeps its metadata. `list_videos` raises `ChannelNotFound` and `fetch_video` raises `VideoUnavailable` for unknown ids. The pipeline also rejects a returned non-English Transcript, and any unexpected per-Video error becomes a transient failure so one Video can't block its Channel. A normal Sync already retries transient failures (the amendment allows it). Reconciliation of "running" Syncs happens whenever a worker takes the lease fresh, so after a crash they resume within `LEASE_SECONDS` (20 s). The UI polls every 2 s until ticket 07 adds SSE.
