# 03: Add and sync a Playlist over the API

**What to build:** Over HTTP, I can resolve a YouTube playlist URL, add it as a Playlist, and run its first Sync. Each of its Videos is ingested and credited to the creator who made it; a creator I haven't added becomes a Channel outside the Library, with an avatar. A Video already on a Library Channel is shared, not duplicated. Syncs now belong to a Channel or a Playlist, and the CLI status and doctor report show Playlist Syncs. See Spec 0004 §Schema, §Sources port, §Playlist Sync, and §Web API.

**Blocked by:** 02 (Channels outside the Library).

**Status:** ready-for-agent

- [ ] Migration adds `playlists` (unique case-insensitive name, unique `youtube_playlist_id`, `indexed`, `check_every_hours`) and `playlist_videos`.
- [ ] `syncs` is rebuilt with nullable `channel_id`, a new `playlist_id`, a CHECK that exactly one is set, and one queued Sync per Playlist. Every existing index is recreated.
- [ ] Lease recovery matches on `(channel_id, playlist_id)`. A test covers a crash while a Playlist Sync is running with another queued.
- [ ] The sources port gains `resolve_playlist`, which runs unpaced. `list_playlist` returns the playlist's title and ordered entries carrying each creator's id and name, and skips entries with no creator id. The Channel playlist filter still works.
- [ ] Missing and private playlists give the single "doesn't exist or is private" message, naming the cookie settings.
- [ ] `FakeTranscriptSource` playlists become `(youtube channel id, video id)` entries resolved against its Channels. The existing playlist-filter test is updated.
- [ ] `POST /playlists/resolve`, `POST /playlists` (409 for a duplicate playlist or a taken name), `GET /playlists` (with counts and creators including `avatar_url`), `GET /playlists/{id}/videos` (in playlist order, with creator, status, and exclusion reason), and `POST /playlists/{id}/syncs` plus retry all work.
- [ ] A Playlist Sync creates unknown creators outside the Library with `check_every_hours` NULL, and paces their avatar lookups. It records Videos, writes memberships and positions, and advances unfinished Videos through the pipeline. Adding a Playlist doesn't start a Sync.
- [ ] A Video shared with a Library Channel stays one row, and either Sync can advance it.
- [ ] The Sync shape keeps `channel_id` and adds `playlist_id` and `source_name`. The web sync helpers, the Syncs list, and the detail page name the source. The CLI status and the doctor's failed-Sync report include Playlist Syncs. The throttle message names the source.
- [ ] Real-yt-dlp check, recorded in the ticket: flat playlist entries carry the creator id, name, and duration, and a private playlist lists with its owner's cookies. The private check needs Drew's cookies, so if they're unavailable, record it as pending and don't block on it.
