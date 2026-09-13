# 07 — Live Sync progress

**What to build:** While a Sync runs, the web UI shows live counts of discovered, per-stage, done, failed, and excluded Videos, and Video rows update their stage as they move. (Story 12.)

**Blocked by:** 04 — Sync: discovery and transcripts

**Status:** ready-for-agent

- [ ] `GET /events` SSE stream emits Sync progress and Video stage changes from the same counters the Sync record holds
- [ ] SSE is proxy-safe: no-buffering headers and periodic keepalive comments
- [ ] Streaming continues while the worker is doing blocking work (no event-loop stalls)
- [ ] UI progress view subscribes and updates live
- [ ] API test observes stage counts over SSE during a fake Sync

From ticket 04 review: `syncs.stage_counts` are Channel-wide counts by current stage (updated after each Video), and `new_videos` counts Videos this Sync discovered. `web/src/Syncs.tsx` and `Videos.tsx` poll every 2 s via `usePolling`; replace that with the SSE stream.
