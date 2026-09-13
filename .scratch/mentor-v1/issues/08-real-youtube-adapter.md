# 08 — Real YouTube adapter

**What to build:** Mentor ingests real YouTube Channels. A yt-dlp-backed TranscriptSource resolves channels, lists Videos, and fetches English captions, while staying polite to YouTube and giving specific failure reasons. (Stories 18–20, real side.)

**Blocked by:** 04 — Sync: discovery and transcripts

**Status:** ready-for-agent

- [ ] Resolves channel URLs and handles to id and display name
- [ ] Flat-lists the videos tab; full metadata and json3 captions fetched per Video with download skipped
- [ ] Delays between requests and backoff on errors, with configurable, documented defaults; optional cookie file path from config
- [ ] Maps members-only, age-restricted, live/upcoming, no-captions, and non-English cases to reasons with a permanent/transient class; PO-token failures name the `bgutil-ytdlp-pot-provider` fix
- [ ] Opt-in `real_youtube` test (skipped by default) fetches captions for one short public Video

From ticket 02:
- Replace the placeholder `YouTubeTranscriptSource` (currently raises SourceUnavailable for everything).
- `resolve_channel` must accept a bare channel id: the web create flow re-resolves the proposal's id server-side.
- Map every yt-dlp failure to ChannelNotFound or SourceUnavailable with a user-facing message; anything else surfaces as an opaque 500.
- Accept only YouTube URLs, @handles, and channel ids before calling yt-dlp, whose generic extractor would fetch arbitrary URLs.

From ticket 06 review:
- The port grew: `list_videos` returns the videos tab newest first (`most_recent` ranks by position), with `VideoListing.published_on` when known and None otherwise; `list_playlist(playlist_id)` returns the playlist's video ids or raises `PlaylistNotFound`.
- A listing date is kept until full details overwrite it, and a Video excluded by a date filter at discovery is never fetched. Pass yt-dlp's approximate ("2 years ago") dates only if they're trustworthy near a filter boundary; None is safe, since the Video is then fetched and judged on its real date.
