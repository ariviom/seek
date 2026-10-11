# 04: Playlists in the Library

**What to build:** In the web app, the Library has a Playlists tab beside Channels and Groups. I can paste a URL, see its title and video count, and add it. The Playlist's page lists its Videos in playlist order, with each creator's avatar (or initials) and name, their pipeline status and any exclusion reason, plus Sync and retry buttons. Creators outside the Library get avatars anywhere the app shows a Channel. See Spec 0004 §Web UI.

**Blocked by:** 03 (Add and sync a Playlist over the API).

**Status:** done

- [x] The Library has a third tab, Playlists, and the URL state carries `playlist` and the `playlists` tab.
- [x] The Add Playlist dialog resolves the URL, shows the title and video count, and confirms. It shows the API's messages for a duplicate, a missing or private playlist, and a taken name.
- [x] The Playlist page has a Videos table with a creator column, live Sync progress, and Sync and retry buttons. It reloads on video and videos events for that Playlist.
- [x] The channel-avatar map also takes creators from `GET /playlists`.
- [x] The Playwright smoke test adds a Playlist, syncs it, and sees its Videos with creators. Typecheck and build pass.

## Comments

**2026-10-10, implemented.**

What landed (web only; no migration and no server change, the ticket 03 API was enough):
- The Library's third tab, Playlists: `PlaylistList` (creators' avatar stack, searchable count, last Sync or live counts), `AddPlaylistDialog` (look up, "Found {title} · N videos", name, Add; the API's messages shown as they come), and `PlaylistPage` (creators, a Videos card with live Sync progress linking to the Sync, Sync now, Retry failed videos, the stage rule, and the Videos table).
- `VideosTable` takes `source: {kind, id}`. For a Playlist it lists in the API's order with a Creator column and reloads on every `video` and `videos` event naming the Playlist.
- URL state carries `playlist` and `tab=playlists`; selecting a Channel, Group, or Playlist clears the other two.
- `App` loads `GET /playlists` up front and reloads it with the Channel counts (on `sync`, `videos`, `ready`); `avatarsOf(channels, playlists)` adds each Playlist's creators to the channel-avatar map.
- `sync-status.playlistSync` beside `channelSync`.

Verification: `uv run pytest -q` 628 passed (627 before, plus the new smoke test), `uv run mypy`, `pnpm --dir web run typecheck`, and `pnpm --dir web run build` clean. No smoke test needed a rerun.

Decisions and readings:
- A Playlist's Videos table has no per-Video Retry. `POST /videos/{id}/retry` answers 404 for a creator outside the Library, so a row button would work for some rows and not others; the page's Retry failed videos covers them all. A Channel's table keeps its per-Video Retry.
- The Playlist's Videos table is always shown, inside the Videos card, instead of behind the Channel page's Videos toggle: the page has nothing else yet.
- The smoke test is a new seventh test, and it asserts the browser's console errors are exactly the three refusals the dialog showed (422 missing or private, 409 duplicate, 409 taken name) instead of none.
- No existing assertion changed. The ticket 03 smoke test only had its "later ticket" comment updated.

For later tickets:
- `PlaylistPage` takes `playlist`, `syncs`, `refresh` (reloads `GET /playlists`), and `onOpenSync`. It has no New chat (06), rename, Pause, or check interval with next check (08), and no delete (09); `LibraryMain` will need an `onRemoved` that clears `playlist` from the selection, as the Channel page has.
- `playlists` is held in `App` but not yet passed to Search (05), the chats folders, scope menu, and `liveScope` (06), or the "Sync all" `syncing` check, which still looks at Channels only (08).
- A Playlist rename doesn't bump `conversationsVersion` yet; `App` watches only Channel names (06/08).
- A Channel page still doesn't reload when a Playlist Sync advances one of its Videos; ticket 07's wider events fix that with no web change, since both tables already match on their own id.
- A creator's avatar reaches the map on the next `GET /playlists` reload, at most a second after the Sync's first `sync` or `videos` event.
- HANDOFF.md's UI conventions don't mention the Playlist components yet (the feature's closing docs pass).
