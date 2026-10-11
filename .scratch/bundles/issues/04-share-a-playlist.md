# 04: Share a Playlist

**What to build:** I export a Playlist with `seek export --playlist NAME_OR_ID FILE` and my friend imports it. They get the Playlist as a search and chat scope, each Video credited to the creator who made it with name and avatar, and those creators kept out of their Library, exactly as if they had added the playlist themselves. A Video in the imported Playlist is searchable even where its Channel's filters would exclude it. See Spec 0005 §The Bundle file (Playlist Bundle), §Export, §Import ("The entry", "Each Video").

**Blocked by:** 03 (Import a Channel Bundle into a Library that already has some of it).

**Status:** done

- [x] `seek export` requires exactly one of `--channel` and `--playlist`. `--playlist` matches a Playlist's name or YouTube playlist id as `seek sync` does.
- [x] A Playlist Bundle holds the Playlist's YouTube playlist id and name, the `done`, non-excluded Videos it includes with each one's position, and each creator they are credited to (YouTube channel id, name, avatar). A Paused Playlist exports the same Videos.
- [x] Import creates a Playlist not yet known, Active and checked daily, under the Bundle's name or `--name`. If another Playlist has that name, import refuses and points at `--name`.
- [x] A Playlist already added keeps its name and settings and gains the memberships it lacked.
- [x] The Playlist includes each Video at the Bundle's position. A Video not yet known is credited to its creator; a creator not yet known becomes a Channel outside the Library, with its avatar under the same host rule as a Channel's; a Video already known keeps the Channel it is credited to.
- [x] Each Video is judged as a Playlist Sync's discovery judges one it includes: only the minimum length can exclude it, and an exclusion by its Channel's filters is lifted. It is then left alone if `done`, and otherwise completed from the Bundle.
- [x] Validation refuses a Playlist Bundle with a Video credited to a creator the Bundle doesn't list.
- [x] After import the Playlist is listed with its creators, is usable as a search scope, and the creators are not offered as scopes. `seek list` shows it as never synced.
- [x] A Sync of the imported Playlist fetches no Transcript for an imported Video. A playlist the recipient can't list fails that Sync with the existing message and removes nothing.
- [x] The report's counts work as for a Channel, with "left out" meaning under the minimum length.
- [x] Tests cover the round trip, positions, creators outside the Library, inclusion winning over a Library Channel's filter, the name clash and `--name`, and merging into a Playlist already added.

## Comments

**2026-10-11, from ticket 02.** Import refuses, as not a Bundle, any `kind` but `channel` and any file where one of the tables it reads is missing or not a plain table (`_meta` and `_TABLES` in `bundles.py`). A Playlist Bundle needs both widened by kind, and its own entry tables checked before the first write as the Channel's are: the playlist id and each creator's id through `_is_youtube_id`, the Playlist's and each creator's name through `_is_name` (`seek list` prints both), each creator once, each avatar under `_AVATAR_HOSTS`, positions as whole numbers, and "credited to a creator the Bundle lists" in place of `_videos`' check against the one Channel.

**2026-10-11, from ticket 03.** Three things in `bundles.py` are shaped for a Channel and need widening here. `_left_out` judges a new Video by the Channel's date range and leaves out one credited to another Channel; a Playlist Bundle judges by the minimum length alone, lifts an exclusion by filters, and fills in a Video whoever it is credited to. `_import_video`'s upsert refuses, by raising, to write over a row that is excluded or credited to a Channel other than the one passed in, so lift the exclusion first and pass the Channel the Video is already credited to. And `ImportReport` and `format_import` name a Channel throughout: the "It was already in the Library" line, the filters line, and `seek sync --channel` in the next step. `--name` is already validated at the top of `import_bundle`.

**2026-10-11, implemented.** `export_playlist(config, playlist, path)` joins `export_channel`, both through one `_export`; `seek export` takes exactly one of `--channel` and `--playlist`. `import_bundle` reads `kind` and merges either. A Playlist Bundle keeps the shared `meta`, `videos`, `transcripts`, and `segments` tables and adds three of its own in place of `channel`: `playlist` (one row: YouTube playlist id, name), `creators` (YouTube channel id, name, avatar), and `playlist_videos` (YouTube video id, position). The format version stays 1, and a Channel Bundle is written exactly as before. Tests are the eight from `test_an_exported_playlist_arrives…` to the end of `tests/test_bundles.py`, and two in `tests/test_cli_lifecycle.py`.

What import prints for a Playlist, the "It was already…" line and the indented ones only when they apply:

```
Imported Sharpening picks: 1 Videos added, 1 already indexed, 2 left out.
  Shorter than the 900 second minimum: 2
It was already in the Library, and keeps its name and settings.
The Bundle's text came from whoever made the file, and is only as trustworthy as they are.
Next, start a Sync to pick up the Videos added to the playlist since: seek sync --playlist PL-picks
```

Readings taken:
- **Validation, all before the knowledge base is opened.** `_meta` takes `playlist` as a kind and requires that kind's tables to be plain ones. `_playlist` holds the id to `_is_youtube_id` and the name to `_is_name`. `_creators` holds each creator to the same id, name, and avatar rules as a Channel Bundle's Channel, each listed once. `_positions` wants one place for every Video, a whole number from 0; places need not be next to each other, since Videos that were not searchable stayed behind, and a place for a Video the Bundle does not list is ignored, as its Transcript would be. `_videos` refuses a Video credited to a creator the Bundle does not list. A creator the Bundle lists with no Video is ignored and never written.
- **The name clash is refused in the entry step**, after validation and before any write: "A Playlist named 'X' already exists; import this one under another name with --name". It matches as the web API does (`COLLATE NOCASE`), and quotes the Library's own Playlist's name, never the Bundle's. In a data directory never started, the knowledge base has been created by then, empty.
- **A Video the Playlist already includes keeps its place.** A Sync's listing gave it, and the ticket says the Playlist "gains the memberships it lacked". A Video gained can therefore share a position with one already there until the next Sync settles the order.
- **Judging is discovery's own code.** `videos.judge_included` was cut out of `record_playlist_discovery` and both call it, so they cannot drift: only the minimum length excludes, and the exclusions it lifts are the four a Channel's filters give (date range either side, Playlist filter, most-recent count), which with the minimum length are every `excluded_reason` Seek stores. A known Video is judged by the length its own row has, as discovery does; one with no length listed that the Bundle shows to be short becomes `done`, and its next Sync excludes it (ticket 03 read a Channel Bundle the same way).
- **A Video that is `done` and searchable is not judged at all**, where discovery would judge it. Judging could only exclude it, for a minimum length raised since it was indexed, and that deletes its Segments; an import never changes a `done` Video, so that is left to its own next Sync. It gains the membership and nothing else. Pinned by `test_a_video_the_friend_has_indexed_is_untouched…`.
- **A new Video under the minimum length is recorded as discovery records it**: a `discovered`, excluded row with its title and length, credited to its creator, included in the Playlist, and counted as left out. A Channel Bundle does not add such a Video; a Playlist Bundle does, since §Import has the Playlist include every Video first.
- **A creator is written only when a new Video is credited to them**, through `channels.credited_channel`, which inserts a Channel outside the Library and touches nothing that exists. A creator already known, in the Library or outside it, keeps its name and avatar.
- **A known Video keeps its credit**: `_import_video` is passed the Channel the row already has, and its guard still refuses a row that is `done`, excluded, or another Channel's.
- `ExportReport.channel_name` is now `name`. `ImportReport` gained `kind` and `created`, and its `channel_name` and `youtube_channel_id` became `name` and `youtube_id`; `filters` is set only for a Channel import created.
- Export refuses "The Playlist 'X' has no indexed Videos to export", and an unknown or ambiguous name with `seek sync`'s own sentences.

Changed on purpose:
- `tests/test_cli_lifecycle.py::test_export_needs_a_channel` is now `test_export_takes_exactly_one_of_a_channel_and_a_playlist`. Its `"the following arguments are required: --channel"` became argparse's sentence for a required either-or, `"one of the arguments --channel --playlist is required"`, with a second case for both given (`"not allowed with argument --channel"`).
- No assertion in `tests/test_bundles.py` from tickets 01 to 03 changed.

Commit security review, on the checkpoints:
1. *A Playlist Bundle fills in a known Video under the Channel it is credited to here, not the creator the Bundle claims, and does not run the Channel branch's `_left_out`.* Acknowledged and accepted: §Import has a known Video keep its Channel in both kinds, and only a Channel Bundle leave a differently credited one untouched. Matching the claimed creator to the local credit would buy nothing, since a hostile Bundle chooses the creator it claims. The invariants that hold, each pinned: a `done` Video is untouched; the Bundle's creator is never written onto a known Video; a Channel already known is never changed.
2. *The exclusion is lifted by the Bundle before it is read as the gate.* Acknowledged and accepted: that is story 33, inclusion winning, and it is discovery's own judgement run by the same function. Only an exclusion by a Channel's filters lifts; `test_a_playlist_bundles_video_is_searchable_whatever_its_channels_filters…` pins both that and a known Video under the minimum length staying left out.
Already decided on tickets 02, 03, and 06 and not reopened: invisible characters reaching a model, a Segment's context and text unchecked against the Transcript, a Bundle completing an unfinished Video, and a Bundle's name and avatar on a Channel known only outside the Library. For a Playlist Bundle the last is narrower: a creator already known keeps what it has.

For later tickets:
- 05: the lease goes where ticket 03 said, after validation and before the entry step, which is now one of two branches (`channels.create_channel` or `_create_playlist`); the per-Video loop is still one loop for both kinds. A Playlist Bundle's Video left out as too short does commit a row, unlike a Channel Bundle's.
- 06: see its comments.
