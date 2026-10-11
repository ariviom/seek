# 10: Playlists in the CLI

**What to build:** From the terminal, I can sync, reindex, and backfill frames for a Playlist by its name or YouTube playlist id. `--all` includes Playlists, and `seek list` shows them. As with Channels, Playlists are added in the web app, not the CLI. See Spec 0004 §CLI.

**Blocked by:** 03 (Add and sync a Playlist over the API).

**Status:** done

- [x] `seek sync`, `seek reindex`, and `seek backfill-storyboards` accept `--playlist NAME_OR_ID`, mutually exclusive with `--all` and `--channel`. Each goes through the running server when there is one, and runs in-process otherwise.
- [x] `--all` covers Active Playlists; for `backfill-storyboards`, every Playlist.
- [x] `seek list` lists Playlists after Groups, with Video counts, creators, and the last Sync.
- [x] The README's CLI and cookie sections cover Playlists, including private playlists through the cookie settings.
- [x] Tests follow the CLI lifecycle and sync-command test patterns.

## Comments

**2026-10-10, implemented.**

What landed (no migration; 22 is still the last):
- `seek sync`, `seek reindex`, and `seek backfill-storyboards` take `--playlist NAME_OR_ID` in the same mutually exclusive group as `--all` and `--channel`. `sync_command.find_playlist` matches the YouTube playlist id or the name, case-insensitively, as `find_channel` does. `sync_channels` and `backfill_storyboards` take `playlist` beside `channel`.
- Sync and reindex of a Playlist go to the running server (`GET /api/playlists`, then `POST /api/playlists/{id}/syncs`) and otherwise run here through `syncs.enqueue` with a Playlist `Source`.
- `storyboards.missing` takes a `Scope` (or None) instead of a Channel id, so the backfill of a Playlist is the Playlist scope of `VIDEO_IN_SCOPE`.
- `seek list` lists Playlists after Groups: the YouTube playlist id, paused or not, ready/failed/excluded counts, the creators, and the last Sync. Ticket 09's note that `seek list` needed nothing was about Channels outside the Library; Playlists were not listed until now.
- README: `--playlist` in the Sync and reindex text, a line on `seek backfill-storyboards` (it had none), `seek list`, and a "Private playlists" note under the cookie settings.

Verification: `uv run pytest -q` 701 passed (681 before); `uv run mypy` and `pnpm --dir web run typecheck` clean. No smoke test needed a rerun. No web change, so no build.

Readings:
- The criterion says each of the three commands goes through the running server. `backfill-storyboards` never does, by design (see `backfill_command`'s docstring), and has no server route; the spec's wording is "runs in-process, as `--channel` does". So `--playlist` there runs in this process, as `--channel` and `--all` do.
- "For `backfill-storyboards`, every Playlist" is the unscoped predicate ticket 05 already put the backfill on: every searchable Video, which includes those of Active Playlists whatever their creators. A Paused Playlist's Videos are fetched only where an Active Library Channel also has them, and `--playlist` on a Paused Playlist stores nothing, as `--channel` on a Paused Channel does. Frames are only ever served for searchable Videos.
- `--all` for sync and reindex already reached Active Playlists through `enqueue_all` (08); a test now pins it through `sync_channels`.

Behaviour that changed:
- `seek sync --all` with nothing to Sync prints "No active Channels or Playlists to Sync." (was "No active Channels to Sync.").
- `seek list` prints its lines when only Playlists exist; "No Channels yet." needs all three to be empty.

Existing assertions changed: `test_the_backfill_offers_only_videos_something_could_cite` passes `Scope("channel", 2)` to `storyboards.missing` where it passed `2`; the expected values are the same.
