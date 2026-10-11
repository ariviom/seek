# 07: Follow the playlist on YouTube

**What to build:** Re-syncing a Playlist follows the playlist on YouTube: added Videos are added, and removed Videos are removed, but never because a listing failed or came back empty. A Video that leaves its last Playlist is deleted, unless a Library Channel still keeps it, in which case it goes back under that Channel's filters. A Video I put in a Playlist is searchable even when a Library Channel's filters would exclude it. See Spec 0004 §Playlist Sync, §Exclusion: inclusion wins, and §The keep rule.

**Blocked by:** 03 (Add and sync a Playlist over the API), 04 (Playlists in the Library).

**Status:** ready-for-agent

- [ ] A re-sync adds new memberships and updates positions. It removes memberships only after a complete listing; an empty listing for a non-empty Playlist fails the Sync and removes nothing.
- [ ] Keep rule: a Video is kept while its Channel is in the Library or any Playlist includes it. An outside-the-Library creator left with no Videos is deleted.
- [ ] Inclusion wins: a Playlist-included Video ignores its Channel's date window, playlist filter, and most-recent count, and takes no most-recent slot. The minimum length still applies.
- [ ] Inline re-judging: a Video that leaves its last Playlist is judged against its Library Channel's minimum length and stored date window. The playlist filter and most-recent rules catch up at that Channel's next Sync.
- [ ] Every video and videos event carries `channel_id` and the ids of the Playlists that include the Video, so both Channel and Playlist pages reload.
- [ ] Retry-failed and reindex on a Playlist act on its Videos, shared ones included.
- [ ] Tests cover additions, removals, failed and empty listings, inclusion wins (date filter and most-recent count), the minimum length, inline re-judging, deletion of an orphaned Video and creator, and events.
