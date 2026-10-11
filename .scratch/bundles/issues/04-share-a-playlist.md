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

## Comments

**2026-10-11, from ticket 02.** Import refuses, as not a Bundle, any `kind` but `channel` and any file where one of the tables it reads is missing or not a plain table (`_meta` and `_TABLES` in `bundles.py`). A Playlist Bundle needs both widened by kind, and its own entry tables checked before the first write as the Channel's are: the playlist id and each creator's id through `_is_youtube_id`, the Playlist's and each creator's name through `_is_name` (`seek list` prints both), each creator once, each avatar under `_AVATAR_HOSTS`, positions as whole numbers, and "credited to a creator the Bundle lists" in place of `_videos`' check against the one Channel.

**2026-10-11, from ticket 03.** Three things in `bundles.py` are shaped for a Channel and need widening here. `_left_out` judges a new Video by the Channel's date range and leaves out one credited to another Channel; a Playlist Bundle judges by the minimum length alone, lifts an exclusion by filters, and fills in a Video whoever it is credited to. `_import_video`'s upsert refuses, by raising, to write over a row that is excluded or credited to a Channel other than the one passed in, so lift the exclusion first and pass the Channel the Video is already credited to. And `ImportReport` and `format_import` name a Channel throughout: the "It was already in the Library" line, the filters line, and `seek sync --channel` in the next step. `--name` is already validated at the top of `import_bundle`.
