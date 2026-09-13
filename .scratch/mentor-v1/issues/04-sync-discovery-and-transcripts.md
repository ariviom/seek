# 04 — Sync: discovery and transcripts

**What to build:** Start a Sync for a Channel from the web UI. It discovers the Channel's Videos, excludes Shorts and too-short Videos, and fetches transcripts and full metadata. The Channel's Video list shows each Video's Pipeline stage and any exclusion or failure reason. Syncs are queued and run one at a time. (Stories 9, 10, 13, 17, 18, 19; uses fakes.)

**Blocked by:** 02 — Mentors and Channels

**Status:** ready-for-agent

- [ ] Discovery is a cheap flat listing of the Channel's videos tab (Shorts are not on it), upserted by YouTube video id
- [ ] Videos under the configurable minimum duration (default 120 s) get stage `excluded` with a reason; they are not failed and not processed
- [ ] Transcript stage fetches English captions as timestamped cues plus full metadata (chapters, description, publish date); Transcript records source and language
- [ ] Members-only, age-restricted, live/upcoming, caption-less, and non-English Videos become `failed` with reason, `failure_stage`, and a permanent/transient class; non-English records the language; the Sync continues
- [ ] `pipeline_stage` records the last completed stage; each stage runs per Video in its own short transaction
- [ ] Sync queue persists in the database, is FIFO, runs one Sync at a time, and dedupes a Channel already queued
- [ ] A lease row prevents a second worker in any process; on startup, Syncs left "running" are reconciled
- [ ] A Channel deleted mid-Sync is skipped without errors or orphan rows
- [ ] Sync record holds per-stage counts and timestamps; Videos list API and UI table show stage, reason, metadata
- [ ] API tests drive all of the above through FakeTranscriptSource

From ticket 01 review:
- Connections use autocommit; add a write-transaction helper using BEGIN IMMEDIATE (`with conn:` does not open a transaction).
- TranscriptSource needs a failure type carrying reason, permanent/transient, and language; decide whether metadata fetch is separate from caption fetch so a caption-less Video keeps its metadata.
- Pick one unknown-id behaviour for the port and make FakeTranscriptSource match; add call recording and per-video error injection.
