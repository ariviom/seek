# 03: Add and sync a Playlist over the API

**What to build:** Over HTTP, I can resolve a YouTube playlist URL, add it as a Playlist, and run its first Sync. Each of its Videos is ingested and credited to the creator who made it; a creator I haven't added becomes a Channel outside the Library, with an avatar. A Video already on a Library Channel is shared, not duplicated. Syncs now belong to a Channel or a Playlist, and the CLI status and doctor report show Playlist Syncs. See Spec 0004 §Schema, §Sources port, §Playlist Sync, and §Web API.

**Blocked by:** 02 (Channels outside the Library).

**Status:** done

- [x] Migration adds `playlists` (unique case-insensitive name, unique `youtube_playlist_id`, `indexed`, `check_every_hours`) and `playlist_videos`.
- [x] `syncs` is rebuilt with nullable `channel_id`, a new `playlist_id`, a CHECK that exactly one is set, and one queued Sync per Playlist. Every existing index is recreated.
- [x] Lease recovery matches on `(channel_id, playlist_id)`. A test covers a crash while a Playlist Sync is running with another queued.
- [x] The sources port gains `resolve_playlist`, which runs unpaced. `list_playlist` returns the playlist's title and ordered entries carrying each creator's id and name, and skips entries with no creator id. The Channel playlist filter still works.
- [x] Missing and private playlists give the single "doesn't exist or is private" message, naming the cookie settings.
- [x] `FakeTranscriptSource` playlists become `(youtube channel id, video id)` entries resolved against its Channels. The existing playlist-filter test is updated.
- [x] `POST /playlists/resolve`, `POST /playlists` (409 for a duplicate playlist or a taken name), `GET /playlists` (with counts and creators including `avatar_url`), `GET /playlists/{id}/videos` (in playlist order, with creator, status, and exclusion reason), and `POST /playlists/{id}/syncs` plus retry all work.
- [x] A Playlist Sync creates unknown creators outside the Library with `check_every_hours` NULL, and paces their avatar lookups. It records Videos, writes memberships and positions, and advances unfinished Videos through the pipeline. Adding a Playlist doesn't start a Sync.
- [x] A Video shared with a Library Channel stays one row, and either Sync can advance it.
- [x] The Sync shape keeps `channel_id` and adds `playlist_id` and `source_name`. The web sync helpers, the Syncs list, and the detail page name the source. The CLI status and the doctor's failed-Sync report include Playlist Syncs. The throttle message names the source.
- [x] Real-yt-dlp check, recorded in the ticket: flat playlist entries carry the creator id, name, and duration, and a private playlist lists with its owner's cookies. The private check needs Drew's cookies, so if they're unavailable, record it as pending and don't block on it.

## Comments

**2026-10-10, implemented.**

What landed:
- Migration 21 (`_playlists`) adds `playlists` and `playlist_videos`, and rebuilds `syncs` with a nullable `channel_id`, `playlist_id`, the exactly-one CHECK, and all three old indexes plus `syncs_playlist_id` and `syncs_one_queued_per_playlist`.
- `videos.Source` (`kind`, `id`) is a Sync's source. Queueing, claiming, counts, retry-failed, reindex, and the `video`/`videos` events take one; `syncs.enqueue` and `syncs.retry_failed` now take a `Source` instead of a Channel id. `ClaimedSync` carries `source` and `youtube_id`.
- Port: `resolve_playlist` (unpaced), `list_playlist` returning `PlaylistListing`, and `resolve_channel(…, paced=True)` for a Sync's avatar lookups. `ports.PLAYLIST_MISSING_OR_PRIVATE` is the one message; `PlaylistNotFound` maps to 422.
- `playlists.py` / `playlists_api.py` (resolve, add, list), the Playlist sync, retry-failed, and videos routes in `syncs_api.py`, and `videos.record_playlist_discovery`. A Playlist Sync judges the Videos it records by the minimum length only.
- Web: the `Sync` type, the Syncs list and page (which retries a Playlist's failed Videos through its own route), and the event types. A sixth Playwright test covers the Syncs list and page for a Playlist.

Verification: `uv run pytest -q` 627 passed (596 before); `uv run mypy`, `pnpm --dir web run typecheck`, and `pnpm --dir web run build` clean.

Real-yt-dlp check (yt-dlp 2026.8.19, `uv run pytest -q -m real_youtube`, 4 passed):
- Flat entries of the public playlist `PLBCF2DAC6FFB574DE` carry `channel_id`, `channel`, and `duration` on every listed entry; its hidden videos come with an id and no creator, and are skipped.
- A missing playlist, and a private one read signed out, both give "The playlist does not exist", so they can't be told apart.
- Private: "Liked videos" (`LL`) is refused signed out and lists with Drew's configured `youtube_cookies_from_browser = "firefox"`. Not pending. The test skips where no cookie setting is configured.

Deviations and readings:
- Lease recovery compares both columns with `IS` inside an `EXISTS`, not the spec's `(channel_id, playlist_id) IN (SELECT …)`. One of the two is always NULL and a row value containing NULL never matches `IN`, so the spec's form matched nothing, for Channel Syncs too (checked on SQLite 3.53). The parametrized restart test covers a Channel and a Playlist.
- The Sync shape's `channel_name` became `source_name` rather than staying beside it, since every consumer names the source now. Assertions in `test_sync`, `test_sync_command`, `test_status_command`, `test_checks`, and `test_cli_lifecycle` were renamed to match.
- The playlist-filter test's missing-playlist assertion now expects the single message, which no longer quotes the playlist id.
- A `video` or `videos` event names its Sync's source: `channel_id` for a Channel, as before, or `playlist_id` for a Playlist. Ticket 07 widens both to the Video's Channel and every Playlist that includes it.
- `new_videos` on a Playlist Sync counts Videos new to the Playlist, including ones a Library Channel had already ingested.

For later tickets:
- A Playlist Sync only adds memberships and updates positions; nothing is removed, and an empty listing just finishes (07).
- A Playlist's Videos credited to creators outside the Library are not searchable until `VIDEO_IN_SCOPE` gains its Playlist half (05).
- A Library Channel's Sync still excludes a Playlist-included Video by its filters, and a Playlist Sync leaves a Video its Channel excluded alone (07, inclusion wins).
- `POST /videos/{id}/retry` still answers 404 for a Video whose creator is outside the Library; the Playlist's retry-failed route is the way to retry it (04 decides what the Videos table offers).
- Deleting a Library Channel still cascades to its Videos, so they drop out of any Playlist that included them (09).
- `enqueue_all` and `enqueue_due` are still Channel-only (08), as are `seek sync`'s targets (10). `GET /playlists` has no next-check field yet (08).
- The doctor's failed-Sync lines need the `playlists` table, so on a database not yet migrated to 21 it reports the count without the lines.
- Creators' avatars are looked up only when the creator is first recorded. A lookup that fails leaves initials until the creator joins the Library and is synced.
- `harness.add_playlist`, `start_playlist_sync`, and `list_playlist_videos` exist; `FakeTranscriptSource.paced_resolves` records a Sync's avatar lookups.
