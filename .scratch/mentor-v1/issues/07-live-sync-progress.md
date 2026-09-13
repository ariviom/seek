# 07 — Live Sync progress

**What to build:** While a Sync runs, the web UI shows live counts of discovered, per-stage, done, failed, and excluded Videos, and Video rows update their stage as they move. (Story 12.)

**Blocked by:** 04 — Sync: discovery and transcripts

**Status:** done

- [x] `GET /events` SSE stream emits Sync progress and Video stage changes from the same counters the Sync record holds
- [x] SSE is proxy-safe: no-buffering headers and periodic keepalive comments
- [x] Streaming continues while the worker is doing blocking work (no event-loop stalls)
- [x] UI progress view subscribes and updates live
- [x] API test observes stage counts over SSE during a fake Sync

From ticket 04 review: `syncs.stage_counts` are Channel-wide counts by current stage (updated after each Video), and `new_videos` counts Videos this Sync discovered. `web/src/Syncs.tsx` and `Videos.tsx` poll every 2 s via `usePolling`; replace that with the SSE stream.

Done note: the stream is `GET /api/events` (under `/api` like every route). `events.Events` is an in-process broker; each message is `data: <json>` with a `type`: `ready` (sent once subscribed; clients reload on it), `sync` (a Sync record, read back in the same transaction that refreshed its counts), `video` (one Video, with `channel_id`, after each stage), `videos` (reload a Channel's Videos: discovery, re-applied exclusions, retry-failed), and `syncs` (reload the Sync list: Mentor renamed or removed, Channel detached). Keepalive comments every 15 s (`create_app(events_keepalive_seconds=...)`); a subscriber more than 10,000 events behind is disconnected and reconnects. Syncs run by another process's worker publish nothing here; the server runs Syncs whenever it is up. The UI shares one EventSource (`web/src/events.ts`, `useLiveList`), applies updates that arrive during a load on top of its result, and reloads on every reconnect; polling is gone. `mentor serve` sets uvicorn's `timeout_graceful_shutdown=5`, since open streams otherwise block shutdown forever. Tests drive the ASGI app directly (`harness.event_stream`) because httpx's ASGI transport buffers whole responses.

Review fixes (both axes): the worker publishes `syncs` after taking the lease (it may have requeued or failed a stopped worker's Syncs) and when it loses the lease; `Cache-Control: no-cache, no-transform`; `useLiveList` retries a failed load after 5 s, since a connected stream sends no `ready`. Correction to the done note: the `video` event's Video is read just after the progress transaction commits, not inside it.

From ticket 07 review (deferred):
- The API publishes a Sync's `queued` record after its transaction returns; if the worker claims it first, the stale `queued` event lands after `running` and shows until the next progress event.
- The UI loads each list twice on first page load (on mount and on `ready`); harmless.
- `web/src/Syncs.tsx` `SHOWN = 50` and `Videos.tsx` `newestFirst` copy the server's list limit and ordering.
- `Events.sync`/`syncs` and `video`/`videos` differ by one letter (a record vs "reload"); the overflow disconnect (`MAX_BACKLOG`) is untested.
