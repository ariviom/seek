# 07: Follow the playlist on YouTube

**What to build:** Re-syncing a Playlist follows the playlist on YouTube: added Videos are added, and removed Videos are removed, but never because a listing failed or came back empty. A Video that leaves its last Playlist is deleted, unless a Library Channel still keeps it, in which case it goes back under that Channel's filters. A Video I put in a Playlist is searchable even when a Library Channel's filters would exclude it. See Spec 0004 §Playlist Sync, §Exclusion: inclusion wins, and §The keep rule.

**Blocked by:** 03 (Add and sync a Playlist over the API), 04 (Playlists in the Library).

**Status:** done

- [x] A re-sync adds new memberships and updates positions. It removes memberships only after a complete listing; an empty listing for a non-empty Playlist fails the Sync and removes nothing.
- [x] Keep rule: a Video is kept while its Channel is in the Library or any Playlist includes it. An outside-the-Library creator left with no Videos is deleted.
- [x] Inclusion wins: a Playlist-included Video ignores its Channel's date window, playlist filter, and most-recent count, and takes no most-recent slot. The minimum length still applies.
- [x] Inline re-judging: a Video that leaves its last Playlist is judged against its Library Channel's minimum length and stored date window. The playlist filter and most-recent rules catch up at that Channel's next Sync.
- [x] Every video and videos event carries `channel_id` and the ids of the Playlists that include the Video, so both Channel and Playlist pages reload.
- [x] Retry-failed and reindex on a Playlist act on its Videos, shared ones included.
- [x] Tests cover additions, removals, failed and empty listings, inclusion wins (date filter and most-recent count), the minimum length, inline re-judging, deletion of an orphaned Video and creator, and events.

## Comments

**2026-10-10, implemented.**

What landed (no migration; 22 is still the last):
- `videos.record_playlist_discovery` follows the listing: after adding memberships and positions it drops the ones the listing no longer has and hands those Videos to the keep rule, in the same transaction. An empty listing for a Playlist that has Videos raises `SourceUnavailable(videos.EMPTY_LISTING)` there, beside the delete, so the Sync fails with that message and the transaction rolls back. A listing that fails never reaches it.
- `videos.apply_keep_rule(conn, video_ids, min_duration_seconds)`, within a transaction, for Videos that just lost what kept them: one a Playlist still includes is left alone; one whose Channel is in the Library is judged inline by the minimum length and the Channel's stored date window; any other is deleted, and then each creator outside the Library left with no Videos is deleted.
- Inclusion wins in every judgement: `_exclusion` takes `included`; a Channel Sync's `_apply_exclusions` skips the date window, playlist filter, and most-recent count for a Playlist-included Video and gives it no most-recent place; the details path (`_exclusion_by_details`) does the same; a Playlist Sync lifts a Channel-filter exclusion from a Video it lists. `_set_exclusion` is the one place a Video gains or loses an exclusion and its Segments.
- Events: `video` and `videos` carry `channel_id` and `playlist_ids` (`videos.Listed`). A `videos` reload is published once per Channel the source's Videos are credited to, with every Playlist that includes any of that Channel's Videos; after a Playlist's listing the Channels credited before it are named too, so a Channel whose Video left the Playlist reloads. Web: the event types and the Playlist table's match (`playlist_ids.includes`).
- Retry-failed and reindex on a Playlist already took shared Videos through ticket 03's `Source`; a test now pins it.

Verification: `uv run pytest -q` 661 passed (645 before); `uv run mypy`, `pnpm --dir web run typecheck`, and `pnpm --dir web run build` clean. No smoke test needed a rerun. The two kept-Video tests were checked to fail with the keep conditions taken out of `apply_keep_rule`.

Behaviour that changed:
- A Playlist Sync can now delete Videos and Channels (see the paths below), and fails on an empty listing where it used to finish.
- A Playlist Sync's `new_videos` counts the Videos added to the Playlist, not the change in its size.
- A Library Channel's Sync no longer excludes a Video a Playlist includes by its date window, playlist filter, or most-recent count; the place such a Video held among the most recent goes to the Channel's next newest at its next Sync.
- `video` and `videos` events lost `playlist_id` and always have `channel_id` and `playlist_ids`. A Playlist with no Videos publishes no `videos` event, since no page lists anything of it.

Existing assertions changed, all in `test_sync_events` and all for the event shape: the Channel `videos` events gained `"playlist_ids": []`; the Playlist test's `videos` and `video` events are now named by the creator's `channel_id` and `playlist_ids` instead of `playlist_id` alone.

What can delete a Video or a Channel now:
- `videos.apply_keep_rule` deletes a Video in no Playlist whose Channel is outside the Library, then that Channel if it credits no Video. Its only caller is `record_playlist_discovery`, for memberships a completed, non-empty listing dropped.
- `channels.delete_channel` (`DELETE /channels/{id}`), unchanged: a Library Channel with all its Videos (09 changes this).

Readings:
- A `videos` event keeps one `channel_id`, as the ticket says, so a Playlist's reload is one event per creator. A Playlist page therefore reloads its table once per creator at each reload point (after the listing, and on a retry). One event with a list of Channels would be a single reload but a different shape from the ticket's.
- A Video YouTube lists without a creator (private or deleted) is not in the port's listing, so it counts as removed. That follows from the spec's Sources port; only a failed or wholly empty listing is protected.
- Inline re-judging can't be shown changing the minimum-length outcome in a test: an included Video is already judged by it.

For later tickets:
- 09: call `videos.apply_keep_rule` with the Video ids read before the Playlist's delete (the memberships cascade), and with a Channel's Video ids after setting `in_library = 0`. It needs `config.min_duration_seconds`. `videos` imports `channels`, so `channels.delete_channel` can't import `videos` at module level; the take-out-of-the-Library flow wants to live in `videos` or be called from the API layer. After either delete, publish `videos.listed_by_creator` for the Channels involved, read before the delete as the Sync does with `videos.creators`.
- 09: here a Video is only ever deleted inside the Playlist's own Sync, before that Sync advances anything, so no Sync meets a Video deleted under it. A delete from the API can run while a Sync does; that case is untested. Inline re-judging there can exclude a Library Channel's Video while that Channel's Sync is advancing it.
- 08: nothing here depends on Pause; inclusion wins whether or not the including Playlist is Active.
- HANDOFF.md's Sync pipeline and Live updates conventions don't describe the keep rule or the event shape yet (the feature's closing docs pass).
