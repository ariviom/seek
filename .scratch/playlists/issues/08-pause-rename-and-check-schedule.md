# 08: Pause, rename, and check schedule

**What to build:** I can pause a Playlist, rename it, and set how often it's checked for changes, just as with a Channel. A pause affects only what I paused: a paused Channel's Videos stay searchable through an Active Playlist, and the reverse holds too. See Spec 0004 §Schema, §Playlist Sync (checks), and §Web UI.

**Blocked by:** 04 (Playlists in the Library), 06 (Chat in a Playlist).

**Status:** done

- [x] `PATCH /playlists/{id}` takes `name` (409 if taken), `indexed`, and `check_every_hours`.
- [x] Renaming updates `scope_name` on the Playlist's Conversations.
- [x] Due checks queue Active Playlists under the same `is_due` rule. A never-synced or Paused Playlist isn't due. "Sync all" covers Active Playlists.
- [x] `GET /playlists` reports the next check.
- [x] Pause semantics in both directions are tested through search.
- [x] The Playlist page has rename, Pause, the check interval, and a next-check line.
- [x] Tests: `is_due` unit cases for Playlists, the app-level due-check test, the PATCH errors, and pause semantics. The smoke test pauses a Playlist.

## Comments

**2026-10-10, implemented.**

What landed (no migration; 22 is still the last):
- `PATCH /playlists/{id}` (`playlists.update_playlist`, `PlaylistUpdate`) takes `name`, `indexed`, and `check_every_hours`, each left unchanged when left out; null turns checks off. A name another Playlist has is 409 "A Playlist named 'X' already exists" (case-insensitive; a Playlist may re-case its own name); an unknown id is 404. A rename updates `conversations.scope_name` where `playlist_id` matches and publishes `syncs`, since Syncs show the name.
- `GET /playlists` (and every Playlist shape) carries `next_check_at`: the latest Sync's `queued_at` plus the interval, which is the moment `is_due` starts passing. It is null while Paused, with checks off, or before the first Sync.
- `syncs.enqueue_due` also selects Playlists, under the same `is_due`; `syncs.enqueue_all` ("Sync all") queues Active Library Channels and then Active Playlists.
- Web: the Playlist page has Rename, Pause/Resume with a Paused badge, the "Check for changes" interval, and the next-check line, built from the Channel page's (`checkLabels` is shared). `App` bumps `conversationsVersion` on Playlist names as well as Channel names, and "Sync all" reads "Syncing…" only once every Active Channel and Playlist has a Sync open. `liveScope`'s paused note for a Playlist ends "Resume it on its page."
- `harness.pause_playlist(client, playlist)` now pauses through the `PATCH`; its five callers moved with it.

Verification: `uv run pytest -q` 666 passed (661 before); `uv run mypy`, `pnpm --dir web run typecheck`, and `pnpm --dir web run build` clean. No smoke test needed a rerun. The rename test was checked to fail with the `scope_name` update taken out.

Behaviour that changed:
- `POST /api/syncs` queues Active Playlists too, so `seek sync` and `seek reindex` with no target already cover them, through the server and in-process (`sync_command` calls `enqueue_all`). Ticket 10 wanted this for `--all`; its `--playlist` target is still to do.
- The automatic checks now queue Syncs for Playlists. Existing Playlists have `check_every_hours` 24, so any already synced more than a day ago is queued at the next server start.

Existing assertions changed:
- `test_checks`: the seed gained four Playlists and three Playlist Syncs, so the "new Syncs" id cut-off moved from 7 to 10 and the expected names and per-source counts include the Playlists. The unit test and `syncs_per_channel` were renamed for "channel or playlist" / "source".
- `test_playlists`: the exact shape of an added Playlist gained `"next_check_at": None`.

Readings:
- `is_due` is one pure function with no notion of what it judges, so there are no separate unit cases for Playlists: the existing parametrized cases are the rule for both, and the test is named for both. The Playlist-specific coverage is the app-level check test (overdue queued; never-synced, Paused, and recent not) and the `next_check_at` test.
- A Channel's next check is still worked out in the browser from the Syncs list; only the Playlist's comes from the server, as the ticket asks.
- The check interval's label is "Check for changes" on a Playlist ("Check for new videos" on a Channel), since a check also removes Videos.

For later tickets:
- 09: `PlaylistPage` still has no delete and `LibraryMain` no `onRemoved` for it; the rename/Pause row is where the Channel page puts Remove (`ml-auto`).
- 10: `enqueue_all` already includes Playlists (see above); `find_channel` and the `--playlist` targets are untouched.
- The Search chips still list Paused Playlists, as the chosen-channels list does Paused Channels.
- HANDOFF.md and the README don't describe Playlist checks yet (the feature's closing docs pass).
