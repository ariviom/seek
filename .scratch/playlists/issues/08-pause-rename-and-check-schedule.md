# 08: Pause, rename, and check schedule

**What to build:** I can pause a Playlist, rename it, and set how often it's checked for changes, just as with a Channel. A pause affects only what I paused: a paused Channel's Videos stay searchable through an Active Playlist, and the reverse holds too. See Spec 0004 §Schema, §Playlist Sync (checks), and §Web UI.

**Blocked by:** 04 (Playlists in the Library), 06 (Chat in a Playlist).

**Status:** ready-for-agent

- [ ] `PATCH /playlists/{id}` takes `name` (409 if taken), `indexed`, and `check_every_hours`.
- [ ] Renaming updates `scope_name` on the Playlist's Conversations.
- [ ] Due checks queue Active Playlists under the same `is_due` rule. A never-synced or Paused Playlist isn't due. "Sync all" covers Active Playlists.
- [ ] `GET /playlists` reports the next check.
- [ ] Pause semantics in both directions are tested through search.
- [ ] The Playlist page has rename, Pause, the check interval, and a next-check line.
- [ ] Tests: `is_due` unit cases for Playlists, the app-level due-check test, the PATCH errors, and pause semantics. The smoke test pauses a Playlist.
