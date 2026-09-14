# 20 — Ingestion reliability

**What to build:** New Videos aren't lost when captions arrive late, one throttled caption fetch doesn't fail a whole Sync, the bot-flag levers are reachable from config, and past livestreams are discovered. From the 2026-09-14 functional review.

**Blocked by:** nothing (independent of 18). Live verification waits for the IP bot-flag from 2026-09-13 to clear.

**Status:** done

- [x] "No captions" (`youtube.caption_track`) is a transient failure, at least while `details.published_on` is within 7 days, so a Video synced before YouTube generates its auto-captions is retried by later Syncs instead of skipped forever (`videos.pending_videos` excludes `failure_permanent = 1`).
- [x] A 403/429 on one caption URL (`ydl.urlopen(track.url)` in `fetch_video`) is a per-Video transient `VideoUnavailable`, not a `SourceUnavailable` that fails the Sync and abandons the remaining Videos. Escalate to a Sync failure only after N consecutive Videos hit it, and have `SyncWorker` cool down (e.g. `youtube_backoff_seconds`, doubling) before claiming the next Sync rather than running into the same wall.
- [x] Config: `youtube_cookies_from_browser` (e.g. `"firefox"`, passed as `cookiesfrombrowser`) and `youtube_extractor_args` (a TOML table merged over the default `skip` args, so `player_client` and `po_token` can be tried without a code change). Document both in README next to the cookie file.
- [x] Jitter (±30%) on the fixed sleeps: `_REQUEST_PAUSE_SECONDS` and `youtube_delay_seconds`.
- [x] Discovery also lists the Channel's `/streams` tab (tolerating its own no-tab error) and merges by YouTube id, so past livestreams are ingested. `video_details` already accepts them.
- [x] Listing stops early when a page holds only known ids, for a Channel with a completed Sync and no most-recent filter; retry-failed does a full listing. Today every Sync (including each timer run) pages the whole `/videos` tab.
- [x] Tests: no-captions retried on a recent Video; a throttled caption fetch fails one Video and the Sync continues; config parsing for the two new keys; streams merged in discovery (`FakeTranscriptSource` grows a `streams` list).

Deferred (M, decide when picking this up): an optional dependency group `mentor[pot]` for `bgutil-ytdlp-pot-provider`, with README setup, so the PO-token failure message points at something installable. Today that message repeats on every Sync with no way through.

Implementation notes (2026-09-14): `VideoUnavailable(throttled=True)` marks a refused caption fetch; `SyncWorker`
stops after `THROTTLE_LIMIT` (3) in a row with a cooldown of `youtube_backoff_seconds` doubling per consecutive
throttled Sync. A throttled Video page (not caption URL) is still `SourceUnavailable` after yt-dlp retries. Streams
are listed after videos (listings carry no dates, so the merged order is per tab). Early stop: `take_until_known`
stops after a full page (30) of known ids; the fake records `listings_known`. The `mentor[pot]` extra was left
deferred.

From ticket 21 review:
- Fixed: Syncs already queued ignored the cooldown (only checked on entering `_drain`); a refused caption request was
  retried by `_call` with backoff before failing its Video; the third refused Video's failure published no event.
- Deferred: `sleep_interval_requests` is jittered once per yt-dlp session, not per request. `_throttled_syncs` resets
  only on a successful Sync, so an unrelated failure between two throttled Syncs keeps the doubling. `take_until_known`
  assumes yt-dlp pages channel tabs 30 at a time (unverified live; a mismatch only loses the saving).
  `config.py` and `youtube.cookies_from_browser` parse the browser spec with two regexes. `caption_track`'s
  `today` default hides a clock in a pure function. `_flat_entries(url)` equals `_tab_entries(url, ())`.
