# 06: Chat in a Playlist

**What to build:** I can start a chat scoped to a Playlist. The model is told it's consulting the Playlist and which creators it holds, its tools are bound to the Playlist, and its Sources and Citations stay inside it. Playlist chats get their own folder, and "Ask about this" always opens a chat the server accepts. See Spec 0004 §Conversations and chat and §Web UI.

**Blocked by:** 05 (Search a Playlist).

**Status:** done

- [x] `conversations` is rebuilt: `scope_kind` admits `playlist`, and a `playlist_id` is added (`ON DELETE SET NULL`). Every current column is carried over.
- [x] `POST /playlists/{id}/conversations` returns 409 for a Paused or empty Playlist, and `GET /conversations?playlist_id=` filters by Playlist.
- [x] The system prompt names "the Playlist 'X' (Channels: …)". The bound MCP server has a `playlist` entry with its own instructions and the tools `list_channels` (its creators), `search`, `expand`, and `get_video`. The scope noun and the "consulted" wording cover `playlist`.
- [x] Citations are restricted to the Playlist's Videos.
- [x] In the web: a folder per Playlist, Playlists in the new-chat menu, and the `playlist` kind in the scope chip and the Conversations filter. The scope wording in the conversation header and folder labels no longer hardcodes Group/Channel.
- [x] "Ask about this": after a Playlist search, the chat opens in that Playlist. Otherwise it opens in the result's Channel if that Channel is in the Library and Active, else in the first Active Playlist (by name) that includes the Video.
- [x] Tests cover creation, the 409s, Citations, bound tools, and the prompt. The smoke test starts a chat in a Playlist through "Ask about this".

## Comments

**2026-10-10, implemented.**

What landed:
- Migration 22 (`_playlist_conversations`) rebuilds `conversations` with `playlist_id` (`ON DELETE SET NULL`), `scope_kind` admitting `playlist`, all eleven old columns, and both old indexes plus `conversations_playlist_id`.
- `POST /playlists/{id}/conversations`: 404 for an unknown Playlist, 409 "is paused, so it can't answer" and 409 "has no Videos yet, so nothing can answer". Empty means no Video is included yet (no `playlist_videos` row), as an empty Group is one with no Channels; a Playlist whose Videos are all still in the pipeline can start a chat. `GET /conversations?playlist_id=`; more than one filter is 422.
- A Conversation's scope id is read from the column its kind names, so a Playlist Conversation is read-only once `playlist_id` is NULL, with the existing "was deleted" message.
- Chat: the prompt's "the Playlist 'X' (Channels: …)" lists the Playlist's creators by name; `mcp_server._BOUND["playlist"]` with `PLAYLIST_INSTRUCTIONS` and `list_channels`, `search`, `expand`, `get_video`. Citations needed no change: `_citations` already goes through `VIDEO_IN_SCOPE`.
- Web: `ScopeKind` gains `playlist`; `liveScope` takes `playlists`; a folder per Playlist, Playlists in the New chat menu, the scope chip, the New chat page's wording and "Who answers" (the creators), the removed-scope wording (`scope.scopeNoun`), New chat on the Playlist page, and "Ask about this".

Verification: `uv run pytest -q` 645 passed (641 before); `uv run mypy`, `pnpm --dir web run typecheck`, and `pnpm --dir web run build` clean. No smoke test needed a rerun.

Behaviour that changed:
- A bound server's instructions now name what it consults. `_SCOPE_INSTRUCTIONS` had `{{consulted}}`, so `.format` left a literal "{consulted}" in every Group and Channel chat's server instructions; it is one brace now. Nothing tested it before; the Playlist chat test does.
- The two-filter message on `GET /conversations` reads "Filter by group_id, channel_id, or playlist_id, not more than one".
- The Chats list's label and empty-state lines say "group, channel, or playlist".
- A Group or Channel chat's syncing note is unchanged; a Playlist chat's names the Playlist when its own Sync is running.

Readings:
- After a Group search "Ask about this" still asks that Group, as before. The spec's "otherwise" (the result's Channel, else a Playlist) applies to Everything and chosen-channels searches.
- A Playlist's creators are listed under "Who answers" without per-creator counts: `GET /playlists` doesn't carry them.

Existing assertions changed: none. `sharpening_picks` moved from `test_search` to the harness so the chat and Conversation tests share it.

For later tickets:
- 08: a rename must update `conversations.scope_name` where `playlist_id` matches, and `App` should then bump `conversationsVersion` on Playlist names as it does for Channel names (it still watches Channels only). The paused note in `scope.liveScope` has no "Resume it on its page" yet, since the page can't. `harness.pause_playlist` is still the only way to pause.
- 09: deleting a Playlist nulls `playlist_id` through the foreign key; the read-only 409 and the web's "The playlist X was removed" alert and Removed folder already cover it but are untested until there is a `DELETE`. `PlaylistPage` still needs `onRemoved`.
- `harness.start_playlist_conversation` exists.
