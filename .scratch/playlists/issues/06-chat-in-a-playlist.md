# 06: Chat in a Playlist

**What to build:** I can start a chat scoped to a Playlist. The model is told it's consulting the Playlist and which creators it holds, its tools are bound to the Playlist, and its Sources and Citations stay inside it. Playlist chats get their own folder, and "Ask about this" always opens a chat the server accepts. See Spec 0004 §Conversations and chat and §Web UI.

**Blocked by:** 05 (Search a Playlist).

**Status:** ready-for-agent

- [ ] `conversations` is rebuilt: `scope_kind` admits `playlist`, and a `playlist_id` is added (`ON DELETE SET NULL`). Every current column is carried over.
- [ ] `POST /playlists/{id}/conversations` returns 409 for a Paused or empty Playlist, and `GET /conversations?playlist_id=` filters by Playlist.
- [ ] The system prompt names "the Playlist 'X' (Channels: …)". The bound MCP server has a `playlist` entry with its own instructions and the tools `list_channels` (its creators), `search`, `expand`, and `get_video`. The scope noun and the "consulted" wording cover `playlist`.
- [ ] Citations are restricted to the Playlist's Videos.
- [ ] In the web: a folder per Playlist, Playlists in the new-chat menu, and the `playlist` kind in the scope chip and the Conversations filter. The scope wording in the conversation header and folder labels no longer hardcodes Group/Channel.
- [ ] "Ask about this": after a Playlist search, the chat opens in that Playlist. Otherwise it opens in the result's Channel if that Channel is in the Library and Active, else in the first Active Playlist (by name) that includes the Video.
- [ ] Tests cover creation, the 409s, Citations, bound tools, and the prompt. The smoke test starts a chat in a Playlist through "Ask about this".
