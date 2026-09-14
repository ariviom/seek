# 20 — Ingestion reliability

**What to build:** New Videos aren't lost when captions arrive late, one throttled caption fetch doesn't fail a whole Sync, the bot-flag levers are reachable from config, and past livestreams are discovered. From the 2026-09-14 functional review.

**Blocked by:** nothing (independent of 18). Live verification waits for the IP bot-flag from 2026-09-13 to clear.

**Status:** todo

- [ ] "No captions" (`youtube.caption_track`) is a transient failure, at least while `details.published_on` is within 7 days, so a Video synced before YouTube generates its auto-captions is retried by later Syncs instead of skipped forever (`videos.pending_videos` excludes `failure_permanent = 1`).
- [ ] A 403/429 on one caption URL (`ydl.urlopen(track.url)` in `fetch_video`) is a per-Video transient `VideoUnavailable`, not a `SourceUnavailable` that fails the Sync and abandons the remaining Videos. Escalate to a Sync failure only after N consecutive Videos hit it, and have `SyncWorker` cool down (e.g. `youtube_backoff_seconds`, doubling) before claiming the next Sync rather than running into the same wall.
- [ ] Config: `youtube_cookies_from_browser` (e.g. `"firefox"`, passed as `cookiesfrombrowser`) and `youtube_extractor_args` (a TOML table merged over the default `skip` args, so `player_client` and `po_token` can be tried without a code change). Document both in README next to the cookie file.
- [ ] Jitter (±30%) on the fixed sleeps: `_REQUEST_PAUSE_SECONDS` and `youtube_delay_seconds`.
- [ ] Discovery also lists the Channel's `/streams` tab (tolerating its own no-tab error) and merges by YouTube id, so past livestreams are ingested. `video_details` already accepts them.
- [ ] Listing stops early when a page holds only known ids, for a Channel with a completed Sync and no most-recent filter; retry-failed does a full listing. Today every Sync (including each timer run) pages the whole `/videos` tab.
- [ ] Tests: no-captions retried on a recent Video; a throttled caption fetch fails one Video and the Sync continues; config parsing for the two new keys; streams merged in discovery (`FakeTranscriptSource` grows a `streams` list).

Deferred (M, decide when picking this up): an optional dependency group `mentor[pot]` for `bgutil-ytdlp-pot-provider`, with README setup, so the PO-token failure message points at something installable. Today that message repeats on every Sync with no way through.
