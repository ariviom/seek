# 05: Search a Playlist

**What to build:** I can search a Playlist from the Search view (a chip per Playlist) or from my own agent over MCP, and "Everything" includes Playlist Videos. Results from creators outside the Library show their avatar and name. See Spec 0004 §Scope resolves to Videos and §MCP (unscoped).

**Blocked by:** 01 (Scope resolves to Videos), 03 (Add and sync a Playlist over the API).

**Status:** ready-for-agent

- [ ] `ScopeKind` gains `playlist`. The scope predicate covers a Playlist's Videos while the Playlist is Active, whether or not their creators are Active or in the Library.
- [ ] A Video is searchable when its Channel is in the Library and Active, or when an Active Playlist includes it. "Everything" covers all searchable Videos.
- [ ] The search request accepts `playlist` by id or name, with at most one of `group`, `channels`, or `playlist`. A Paused Playlist returns no results.
- [ ] MCP `search` takes `playlist`. The new `list_playlists` returns Active Playlists with their creators and searchable Video counts. The `sql` tool's table list describes `playlists`, `playlist_videos`, and `in_library`.
- [ ] Search results carry the ids of the Active Playlists that include them, which ticket 06 uses for "Ask about this".
- [ ] The Search view has a chip per Playlist after the Groups, and the results header names the Playlist.
- [ ] Tests cover Playlist scope, "Everything", name lookup, and the MCP tools. The smoke test searches a Playlist.
