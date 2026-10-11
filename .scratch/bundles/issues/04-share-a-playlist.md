# 04: Share a Playlist

**What to build:** I export a Playlist with `seek export --playlist NAME_OR_ID FILE` and my friend imports it. They get the Playlist as a search and chat scope, each Video credited to the creator who made it with name and avatar, and those creators kept out of their Library, exactly as if they had added the playlist themselves. A Video in the imported Playlist is searchable even where its Channel's filters would exclude it. See Spec 0005 §The Bundle file (Playlist Bundle), §Export, §Import ("The entry", "Each Video").

**Blocked by:** 03 (Import a Channel Bundle into a Library that already has some of it).

**Status:** ready-for-agent

- [ ] `seek export` requires exactly one of `--channel` and `--playlist`. `--playlist` matches a Playlist's name or YouTube playlist id as `seek sync` does.
- [ ] A Playlist Bundle holds the Playlist's YouTube playlist id and name, the `done`, non-excluded Videos it includes with each one's position, and each creator they are credited to (YouTube channel id, name, avatar). A Paused Playlist exports the same Videos.
- [ ] Import creates a Playlist not yet known, Active and checked daily, under the Bundle's name or `--name`. If another Playlist has that name, import refuses and points at `--name`.
- [ ] A Playlist already added keeps its name and settings and gains the memberships it lacked.
- [ ] The Playlist includes each Video at the Bundle's position. A Video not yet known is credited to its creator; a creator not yet known becomes a Channel outside the Library, with its avatar under the same host rule as a Channel's; a Video already known keeps the Channel it is credited to.
- [ ] Each Video is judged as a Playlist Sync's discovery judges one it includes: only the minimum length can exclude it, and an exclusion by its Channel's filters is lifted. It is then left alone if `done`, and otherwise completed from the Bundle.
- [ ] Validation refuses a Playlist Bundle with a Video credited to a creator the Bundle doesn't list.
- [ ] After import the Playlist is listed with its creators, is usable as a search scope, and the creators are not offered as scopes. `seek list` shows it as never synced.
- [ ] A Sync of the imported Playlist fetches no Transcript for an imported Video. A playlist the recipient can't list fails that Sync with the existing message and removes nothing.
- [ ] The report's counts work as for a Channel, with "left out" meaning under the minimum length.
- [ ] Tests cover the round trip, positions, creators outside the Library, inclusion winning over a Library Channel's filter, the name clash and `--name`, and merging into a Playlist already added.
