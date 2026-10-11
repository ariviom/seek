# 10: Playlists in the CLI

**What to build:** From the terminal, I can sync, reindex, and backfill frames for a Playlist by its name or YouTube playlist id. `--all` includes Playlists, and `seek list` shows them. As with Channels, Playlists are added in the web app, not the CLI. See Spec 0004 §CLI.

**Blocked by:** 03 (Add and sync a Playlist over the API).

**Status:** ready-for-agent

- [ ] `seek sync`, `seek reindex`, and `seek backfill-storyboards` accept `--playlist NAME_OR_ID`, mutually exclusive with `--all` and `--channel`. Each goes through the running server when there is one, and runs in-process otherwise.
- [ ] `--all` covers Active Playlists; for `backfill-storyboards`, every Playlist.
- [ ] `seek list` lists Playlists after Groups, with Video counts, creators, and the last Sync.
- [ ] The README's CLI and cookie sections cover Playlists, including private playlists through the cookie settings.
- [ ] Tests follow the CLI lifecycle and sync-command test patterns.
