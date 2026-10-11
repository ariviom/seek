# 05: Search a Playlist

**What to build:** I can search a Playlist from the Search view (a chip per Playlist) or from my own agent over MCP, and "Everything" includes Playlist Videos. Results from creators outside the Library show their avatar and name. See Spec 0004 §Scope resolves to Videos and §MCP (unscoped).

**Blocked by:** 01 (Scope resolves to Videos), 03 (Add and sync a Playlist over the API).

**Status:** done

- [x] `ScopeKind` gains `playlist`. The scope predicate covers a Playlist's Videos while the Playlist is Active, whether or not their creators are Active or in the Library.
- [x] A Video is searchable when its Channel is in the Library and Active, or when an Active Playlist includes it. "Everything" covers all searchable Videos.
- [x] The search request accepts `playlist` by id or name, with at most one of `group`, `channels`, or `playlist`. A Paused Playlist returns no results.
- [x] MCP `search` takes `playlist`. The new `list_playlists` returns Active Playlists with their creators and searchable Video counts. The `sql` tool's table list describes `playlists`, `playlist_videos`, and `in_library`.
- [x] Search results carry the ids of the Active Playlists that include them, which ticket 06 uses for "Ask about this".
- [x] The Search view has a chip per Playlist after the Groups, and the results header names the Playlist.
- [x] Tests cover Playlist scope, "Everything", name lookup, and the MCP tools. The smoke test searches a Playlist.

## Comments

**2026-10-10, implemented.**

What landed (no migration; ticket 03's tables were enough):
- `ScopeKind` gains `playlist`. `scope.VIDEO_IN_SCOPE` is still the one predicate: a Video is searchable when it is done, not excluded, and either on an Active Library Channel or in an Active Playlist. A Channel or Group scope keeps requiring the Active Library Channel; a Playlist scope requires only the Active Playlist. `CHANNEL_IN_SCOPE` names a Playlist's creators, so `channel_summaries(conn, Scope("playlist", id))` lists them with their counts.
- Search takes `playlist` (id or name), with at most one of `group`, `channels`, `playlist`. Results carry `playlist_ids`, the Active Playlists that include the Video, in id order (`scope.ACTIVE_PLAYLIST_IDS`).
- MCP: `search(playlist=…)`, `list_playlists` (`playlists.playlist_summaries`: Active Playlists as `{id, name, video_count, creators: [{id, name, video_count}]}`), the `sql` table list, and the server instructions. The README's tool list follows.
- `storyboards.read_frames` and `missing` are on `VIDEO_IN_SCOPE`, so a Playlist's Videos have frames whatever their creators, and `seek backfill-storyboards` with no `--channel` fetches them.
- Web: a chip per Playlist after the Groups (`useSearch` takes `playlists`), and the results header names the Playlist.

Verification: `uv run pytest -q` 641 passed (628 before); `uv run mypy`, `pnpm --dir web run typecheck`, and `pnpm --dir web run build` clean. No smoke test needed a rerun.

Behaviour that changed:
- Every search result has a `playlist_ids` field, over HTTP and MCP.
- The scope-conflict message is now "Search a Group, a list of Channels, or a Playlist, not more than one" (was "…, not both").
- Frames and the backfill now follow the predicate exactly: a Video that is excluded, or credited to a Channel outside the Library and in no Active Playlist, gets none. Before, they only tested `channels.indexed` and `done`.
- Chosen channels are still searched as Channels: a Paused one gives nothing even where an Active Playlist keeps its Videos searchable under Everything. Search adds `channels.indexed = 1` to that filter for this.

Existing assertions changed: the exact result in `test_search` and `SEARCH_RESULT_FIELDS` in `test_storyboards` gained `playlist_ids`; `TOOLS` in `test_mcp` and `test_mcp_config` gained `list_playlists`; `test_invalid_searches_are_tool_errors` expects the new conflict message.

For later tickets:
- "Ask about this" is untouched (06): it still opens the searched Group, else the result's Channel, so after a Playlist search a result from a creator outside the Library asks a Channel the server answers 404 for. The search outcome carries only `groupId`; 06 adds the Playlist and uses `playlist_ids`.
- `mcp_server._BOUND` has no `playlist` entry, so `create_scope_server` with a Playlist scope raises `KeyError` until 06 adds it. `SCOPE_NOUN` already has "Playlist".
- A Paused Playlist can only be made in tests through `harness.pause_playlist`, which writes `indexed = 0` directly until 08's `PATCH`. `harness.sync_playlist` syncs a Playlist and checks it finished.
- The Search chips list every Playlist, Paused or not, as the chosen-channels list does Channels. The Everything header still reads "every channel".
- `storyboards.missing` still takes a Channel id; 10's `--playlist` can pass a Playlist scope to the same predicate.
