# 09: Delete a Playlist; creators joining and leaving the Library

**What to build:** Deleting a Playlist keeps any Video a Library Channel or another Playlist still includes, and leaves its chats readable but not continuable. Deleting a Channel whose Videos a Playlist still includes takes it out of the Library instead, keeping those Videos. Its old chats stay read-only even if I add the creator again. Adding a creator who already exists outside the Library brings that same Channel into the Library and reuses their indexed Videos. See Spec 0004 §The keep rule.

**Blocked by:** 06 (Chat in a Playlist), 07 (Follow the playlist on YouTube).

**Status:** done

- [x] `DELETE /playlists/{id}` reads its Video ids before the cascade, applies the keep rule and inline re-judging, and forgets creators left with no Videos. Its Conversations become read-only.
- [x] Deleting a Library Channel that a Playlist still uses sets `in_library = 0` and clears its filters. It also removes its Group memberships and Syncs, nulls its Conversations' `channel_id`, and applies the keep rule to its other Videos. Deleting one that no Playlist uses works as before.
- [x] `POST /channels` for a creator outside the Library brings it into the Library with the given name, default filters, and the default check interval, instead of returning a conflict. Its first Sync is the user's.
- [x] Deletion is available from the Playlist page.
- [x] Tests cover each path, including read-only chats after re-adding a creator.

## Comments

**2026-10-10, implemented.**

What landed (no migration; 22 is still the last):
- `DELETE /playlists/{id}` (`playlists.delete_playlist`): in one transaction it reads the Playlist's Video ids and creators, deletes the Playlist (its memberships and Syncs cascade, its Conversations' `playlist_id` goes NULL), and hands the ids to `videos.apply_keep_rule`. An unknown id is 404.
- `DELETE /channels/{id}` now goes through `videos.delete_channel` (`channels.delete_channel` is gone; `videos` imports `channels`, so the flow lives there). With no Video in any Playlist the Channel is deleted as before. Otherwise `channels.leave_library` sets `in_library = 0`, clears the four filter columns, deletes its Group memberships and Syncs, and nulls its Conversations' `channel_id`; then the keep rule runs over all its Video ids, read before anything was deleted.
- `channels.create_channel` brings a Channel that exists outside the Library into it: same row and id, the given name (or its YouTube name), no filters, `check_every_hours` 24, and no Sync queued. One already in the Library is still 409.
- Both deletes publish `syncs` and then a `videos` event per Channel whose Videos remain (`videos.listed_by_creator`), so open Channel and Playlist pages and the counts reload.
- Web: Remove playlist on the Playlist page, built from the Channel page's (`ConfirmDialog`, `api.deletePlaylist`, `LibraryMain`'s `onRemoved` clearing `playlist`). The Channel's confirmation now adds "Videos a playlist includes stay."

Verification: `uv run pytest -q` 681 passed (666 before); `uv run mypy`, `pnpm --dir web run typecheck`, and `pnpm --dir web run build` clean. No smoke test needed a rerun. The kept-Video tests were checked to fail with either keep condition taken out of `apply_keep_rule`, and the re-add test with the `channel_id` nulling taken out.

Tests: `tests/test_keep_rule.py` (twelve: what stays first, then what goes, the Channel leaving and joining the Library, and four deletes arriving mid-Sync), two in `test_conversations` (read-only after a Playlist is deleted, which was 06's untested path, and after a Channel leaves and is added again), one in `test_sync_events`, and the Playlist smoke test now removes the Playlist and reads its chat under Removed.

Behaviour that changed:
- Deleting a Channel no longer takes its Videos out of Playlists: one a Playlist draws on stays as a creator outside the Library with those Videos, and its id is kept. Adding it again gives the same id, where a deleted Channel's id was never reused before; its old Conversations stay read-only because their `channel_id` was nulled.
- `POST /channels` answers 201, not 409, for a creator known only through a Playlist.
- Deleting a Channel or a Playlist publishes `videos` events as well as `syncs`.

Existing assertions changed: none. The Playlist smoke test gained steps at its end.

What can delete a Video or a Channel now:
- `videos.apply_keep_rule`: a Video in no Playlist whose Channel is outside the Library, then that Channel if it credits no Video. Callers: `record_playlist_discovery` (memberships a completed, non-empty listing dropped), `playlists.delete_playlist` (the deleted Playlist's Videos), and `videos.delete_channel` (the Videos of a Channel just taken out of the Library).
- `videos.delete_channel`: a Library Channel with every Video of its own, by cascade, only when no Playlist includes any of them.
- `playlists.delete_playlist` deletes the Playlist row itself; Videos go only through the keep rule above.

Readings:
- A Channel brought into the Library is also made Active (`indexed = 1`) and takes the avatar the lookup offers when it has one. The spec lists the name, default filters, and check interval; without this a Channel that left the Library while Paused would come back Paused, unlike any other newly added Channel.
- Taking a Channel out of the Library leaves its name, avatar, `indexed`, and `check_every_hours` as they were; nothing reads the last two for a Channel outside the Library.
- "Was deleted, so this Conversation is read-only" is also what a Conversation says when its Channel left the Library.

Deletes during a Sync (all held on a fetch with `Gate`):
- A Playlist deleted during its own Sync, and a Channel taken out during its own: the Sync row goes, the worker meets a gone Video or Sync and stops, nothing is left behind, and the next queued Sync runs.
- A Channel taken out while a Playlist's Sync fetches its Video: the Video is kept and that Sync finishes it.
- A Playlist deleted while a Library Channel's Sync fetches a Video only the Playlist kept inside the Channel's filters: the Video ends excluded by the Channel's date window and the Sync finishes.
- Not covered, because only a fetch can be held: a Playlist deleted between a Video's segmentation and its done mark in a running Sync, where inline re-judging excludes the Video. The Sync's remaining stage writes then leave it marked done while excluded, with no Segments. It is not searchable (it is excluded), and the Channel's next Sync steps it back. Only if the exclusion is lifted before that Sync does it stay done with no Segments until a reindex.

For later tickets:
- 10: nothing here touches the CLI. `seek list` reads `/api/channels` or `channels.list_channels`, both Library-only, so a Channel that left the Library is already absent from it; a deleted Playlist's Syncs are gone from `seek status`, since they cascade.
- `harness.take_out_of_library` still writes `in_library = 0` directly; the tests that use it predate the real path and don't need a Playlist.
- Closing docs pass: HANDOFF.md's conventions still say `group_id`/`channel_id` are "SET NULL on delete" only, and don't mention `videos.delete_channel`, `channels.leave_library`, the bring-in on `create_channel`, or that `channels_router` and `playlists_router` take `min_duration_seconds`. The README has nothing on removing a Playlist or on a removed Channel staying as a creator.
