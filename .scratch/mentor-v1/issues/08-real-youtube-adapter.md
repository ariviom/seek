# 08 — Real YouTube adapter

**What to build:** Mentor ingests real YouTube Channels. A yt-dlp-backed TranscriptSource resolves channels, lists Videos, and fetches English captions, while staying polite to YouTube and giving specific failure reasons. (Stories 18–20, real side.)

**Blocked by:** 04 — Sync: discovery and transcripts

**Status:** done

- [x] Resolves channel URLs and handles to id and display name
- [x] Flat-lists the videos tab; full metadata and json3 captions fetched per Video with download skipped
- [x] Delays between requests and backoff on errors, with configurable, documented defaults; optional cookie file path from config
- [x] Maps members-only, age-restricted, live/upcoming, no-captions, and non-English cases to reasons with a permanent/transient class; PO-token failures name the `bgutil-ytdlp-pot-provider` fix
- [x] Opt-in `real_youtube` test (skipped by default) fetches captions for one short public Video

From ticket 02:
- Replace the placeholder `YouTubeTranscriptSource` (currently raises SourceUnavailable for everything).
- `resolve_channel` must accept a bare channel id: the web create flow re-resolves the proposal's id server-side.
- Map every yt-dlp failure to ChannelNotFound or SourceUnavailable with a user-facing message; anything else surfaces as an opaque 500.
- Accept only YouTube URLs, @handles, and channel ids before calling yt-dlp, whose generic extractor would fetch arbitrary URLs.

From ticket 06 review:
- The port grew: `list_videos` returns the videos tab newest first (`most_recent` ranks by position), with `VideoListing.published_on` when known and None otherwise; `list_playlist(playlist_id)` returns the playlist's video ids or raises `PlaylistNotFound`.
- A listing date is kept until full details overwrite it, and a Video excluded by a date filter at discovery is never fetched. Pass yt-dlp's approximate ("2 years ago") dates only if they're trustworthy near a filter boundary; None is safe, since the Video is then fetched and judged on its real date.

Done note: `youtube.YouTubeTranscriptSource(YouTubeSettings)` against yt-dlp 2026.8.19 (`yt-dlp[default]`, which brings `yt-dlp-ejs`; Deno on PATH solves YouTube's JS challenges). `channel_url` accepts only @handles, `UC…` ids, and youtube.com `/@handle`, `/channel/`, `/c/`, `/user/` URLs, and rebuilds a canonical URL, so user text never reaches yt-dlp. Resolve and listing use `extract_flat="in_playlist"` on `/videos`; a channel with no videos tab resolves to ChannelNotFound and lists as empty. Listing dates are left None (yt-dlp's are approximate). `fetch_video` extracts with `process=False` (no format selection, so withheld formats can't fail it), then picks manual English subtitles, else the automatic `<lang>-orig` track when it is English; any other spoken language is a permanent failure with that language, and missing captions after a PO-token warning are a transient failure naming `bgutil-ytdlp-pot-provider`. Transcript language is normalised to `en`. `classify_error` maps yt-dlp messages to not_found / unavailable (permanent or transient) / throttled / unreachable / other; throttled and unreachable retry with doubling backoff, then raise SourceUnavailable, which stops the Sync. Config: `youtube_delay_seconds` (10, measured from the end of the previous request; resolving for the web UI doesn't wait), `youtube_retries` (3), `youtube_backoff_seconds` (30), `youtube_cookie_file` (absolute path, optional). Parsing and classification are pure functions tested in `tests/test_youtube.py`; `uv run pytest -m real_youtube` runs the live test ("Me at the zoo"), excluded by default through `addopts`.
