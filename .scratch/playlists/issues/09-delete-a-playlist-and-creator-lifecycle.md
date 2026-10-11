# 09: Delete a Playlist; creators joining and leaving the Library

**What to build:** Deleting a Playlist keeps any Video a Library Channel or another Playlist still includes, and leaves its chats readable but not continuable. Deleting a Channel whose Videos a Playlist still includes takes it out of the Library instead, keeping those Videos. Its old chats stay read-only even if I add the creator again. Adding a creator who already exists outside the Library brings that same Channel into the Library and reuses their indexed Videos. See Spec 0004 §The keep rule.

**Blocked by:** 06 (Chat in a Playlist), 07 (Follow the playlist on YouTube).

**Status:** ready-for-agent

- [ ] `DELETE /playlists/{id}` reads its Video ids before the cascade, applies the keep rule and inline re-judging, and forgets creators left with no Videos. Its Conversations become read-only.
- [ ] Deleting a Library Channel that a Playlist still uses sets `in_library = 0` and clears its filters. It also removes its Group memberships and Syncs, nulls its Conversations' `channel_id`, and applies the keep rule to its other Videos. Deleting one that no Playlist uses works as before.
- [ ] `POST /channels` for a creator outside the Library brings it into the Library with the given name, default filters, and the default check interval, instead of returning a conflict. Its first Sync is the user's.
- [ ] Deletion is available from the Playlist page.
- [ ] Tests cover each path, including read-only chats after re-adding a creator.
