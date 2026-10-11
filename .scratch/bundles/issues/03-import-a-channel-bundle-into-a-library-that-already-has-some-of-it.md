# 03: Import a Channel Bundle into a Library that already has some of it

**What to build:** Importing a Channel I already have, or whose Videos I partly have, never overwrites my own work and never replaces my settings. Videos I've finished indexing stay exactly as they are; ones I have but haven't finished are completed from the Bundle; my own rules decide what is left out. A second import of a newer Bundle is a cheap top-up, and import tells me what happened to every Video. See Spec 0005 §Import ("The entry", "Each Video", the report).

**Blocked by:** 01 (Share a Channel with someone who doesn't have it).

**Status:** done

- [x] A Channel already in the Library keeps its name, filters, Pause state, check schedule, and avatar.
- [x] A Channel known only outside the Library is brought into it under the Bundle's name, keeping its Videos, with the Bundle's date range and most-recent count applied after it is brought in.
- [x] `--name NAME` names the entry when import creates it. When the entry already exists, import says it kept the existing name. An imported Channel may share a name with another, as one added in the web UI may.
- [x] A Video already `done` is left untouched.
- [x] A Video that is known but unfinished (discovered, mid-pipeline, or failed, including permanently) takes its details, Transcript, Segments, and vectors from the Bundle, has its failure cleared, and becomes `done`.
- [x] A Video not yet known is judged by the recipient's minimum length and by the date range in force on the Channel after the entry step. One they exclude is not added.
- [x] A Video already known is not judged again: one that is excluded stays excluded and untouched, including one excluded by a most-recent count or a Playlist filter.
- [x] A known, unfinished Video that one of the recipient's Playlists includes is completed from the Bundle whatever the Channel's filters say.
- [x] A Video credited here to a different Channel than the Bundle says keeps its credit, is left untouched, and is reported.
- [x] Import prints any filters that arrived with a new Channel and one count per outcome, every Video in the Bundle falling in exactly one: added (became `done` from the Bundle, new or completed), already indexed, and left out, with a count per reason.
- [x] Importing the same Bundle twice changes nothing the second time. Importing a larger Bundle of the same Channel adds only the new Videos.
- [x] Tests cover each rule above through the import function and the app's surfaces, including a Bundle that produces all three counts.

## Comments

**2026-10-11, implemented.** `import_bundle(config, path, name=None)` now merges. Ticket 02's validation is untouched and still runs over the whole Bundle before the knowledge base is opened. Then the entry step: a Channel in the Library is used as it is, and any other goes through `channels.create_channel` with `name` and the Bundle's filters, which is also what brings a creator in from outside the Library. Then each Video in a transaction of its own: `_left_out` gives the reason it is not filled in, a `done` one is counted and skipped, and `_import_video` fills in the rest, by insert or over the unfinished row. `_known` and its refusal are gone. `seek import` takes `--name NAME`. Tests are the eleven from `test_import_says_what_it_added…` to `test_a_larger_bundle_of_a_channel_already_imported…` in `tests/test_bundles.py` (ticket 01's `test_an_imported_segment_is_found…` sits among them), and the CLI round trip.

What import prints now, the indented and the "It …" lines only when they apply:

```
Imported Paul Wright: 1 Videos added, 1 already indexed, 2 left out.
  Shorter than the 900 second minimum: 1
  Credited here to another Channel: 1
It was already in the Library, and keeps its name and settings.
It arrived with its filters: published from 2023-01-01, the 25 most recent.
The Bundle's text came from whoever made the file, and is only as trustworthy as they are.
Next, start a Sync to pick up the Videos published since: seek sync --channel UC-wright
```

Readings taken:
- **The first line always carries all three counts**, in the voice of `seek list` ("2 ready, 0 failed, 0 excluded"). Ticket 01's "searchable now" went with it, since it read wrongly beside "0 Videos added".
- **A reason left out is Seek's own exclusion sentence**, the one the Videos table shows: a new Video's from `videos.exclusion` (made public for this, it was `_exclusion`), a known one's as its own Sync stored it. The one new sentence is "Credited here to another Channel". Reasons are listed in the order the Bundle first meets them.
- **"Kept the existing name" is said whenever the Channel was already in the Library**, with `--name` or without, as one sentence that also covers its settings. The filters line is for a Channel import added, including one brought in from outside the Library, and is left off when the Bundle carries no date range or count. It uses the web UI's wording for a Channel's filters.
- **`--name` is held to the web API's `Name`** (trimmed, 1 to 200 characters) before the file is opened, and refused with "A name is 1 to 200 characters". It is checked even when the Channel turns out to exist and the name goes unused.
- **A new Channel's own date range leaves Videos out at import.** A Bundle carries Videos that were searchable only through one of the sender's Playlists; those outside the date range the Bundle brings are not added, since the range is in force once the entry step has run (§Import). §Export's "at the next Sync" then holds only for the most-recent count.
- **A known, unfinished Video is not judged at all**, as the spec says, the minimum length included. One discovered here with no length listed, which the Bundle shows to be under the minimum, becomes `done`; the Channel's next Sync excludes it.
- **A Channel is added even when none of the Bundle's Videos end up under it** (all credited elsewhere, or all left out). The entry step does not look ahead.
- **A creator brought in from outside the Library** takes the Bundle's avatar when it has one YouTube serves, and otherwise keeps the one it had. That is `create_channel` as it stood.
- **A Video filled in keeps** the Channel it was credited to, when it was discovered, and any storyboard. Its Segments are deleted and the Bundle's inserted, so the triggers drop the old vectors and lexical rows.
- **The write holds the rule too.** `_import_video`'s upsert only updates a row that is credited to the Channel, not `done`, and not excluded, and raises otherwise, so the decision above it is not the only thing between a Bundle and a finished Video. No seam reaches that branch; checked by hand, by switching the `done` check off and watching the second import raise instead of overwrite.
- **The entry lookup and the insert are two steps.** A Channel added on the server between them is the `Conflict` `cli.import_` already catches.
- "Mid-pipeline" is pinned by a Video that was cut into Segments and then failed at embedding, and by one never fetched. A Sync interrupted between stages with no failure recorded takes the same path and has no test of its own.
- `stored()` in the tests reads the knowledge base's rows directly. It is used only where "nothing was written" is the behaviour: the second import, a `done` Video, an excluded Video, and the row of a Channel already in the Library.

Changed on purpose:
- `test_import_says_what_it_added_and_what_to_do_next_and_refuses_a_channel_already_known` is now `…_and_importing_the_bundle_again_changes_nothing`. Its `pytest.raises(…, match="already has the Channel 'Paul Wright'")` on the second import became: the second import reports 0 added and 2 already indexed, says the Channel keeps its name and settings, and leaves every row as it was. The first line of `format_import` changed from "2 Videos added, searchable now." to "2 Videos added, 0 already indexed, 0 left out."
- `test_import_refuses_a_bundle_whose_videos_the_library_credits_to_another_channel_and_writes_nothing` is now `test_a_video_the_library_credits_to_another_channel_keeps_its_credit_and_is_reported_as_left_out`. Its `pytest.raises(…, match="already has the Channel 'Wood By Wright' (UC-wright) or some")` and `channels == []` became: the import succeeds, Wood By Wright is added with the one Video that is its own, and the report counts one left out as credited to another Channel. The assertion that the Playlist's Video is still Rex Krueger's and `done` stays, and now also checks its own words are still what search finds.
- The CLI round trip in `tests/test_cli_lifecycle.py`: the second `import`, which asserted `SystemExit` with "seek: This knowledge base already has the Channel 'Wood By Wright'", now succeeds with `--name` and asserts the two lines saying nothing was added and the name was kept. The import refusal that exits with one `seek:` sentence is asserted on a file that is not there instead. `imported.splitlines()[0]` changed with the first line, and with `--name "Paul Wright"` on the first import.
- `test_a_channel_whose_name_joins_an_emoji_imports_and_is_listed_under_that_name`: the first line of `format_import`, as above.

Commit security review, on the checkpoints:
1. *Exclusion filters ignored on merge* (flagged while the recipient's rules were still to do). Fixed: a known Video that is excluded, by whichever rule, is never filled in; a new one the minimum length or the Channel's date range excludes is not added; and the write refuses a row that is `done`, excluded, or another Channel's. Pinned by `test_a_video_the_friends_own_sync_excluded_stays_excluded_whichever_filter_excluded_it` (minimum length, date range, Playlist filter, most-recent count, with no row written) and the two "not added" tests.
2. *A Bundle's text written into a Channel the Library already has.* Acknowledged and accepted: the spec has an unfinished Video take its details, Transcript, Segments, and vectors from the Bundle, and it is part of the unsigned-Bundle risk. The invariant that holds is that a `done` Video is untouched, row for row, vectors included.
3. *A Bundle's name, avatar, and filters written to a Channel known outside the Library.* Acknowledged and accepted: the spec brings such a Channel in as adding it would. The invariant that holds is the other half: nothing of the Bundle's reaches the row of a Channel already in the Library.

For later tickets:
- 04: see its comments.
- 05: running the import again is already the resume, and `done` Videos are skipped. The lease belongs after validation and before the entry step, which is the first write. The loop in `import_bundle` is where the callback goes; decide whether it is called for a Video left out or already indexed, which commits nothing.
- 06: see its comments. The README should show the report above, say that a second import of a newer Bundle is a top-up, and give the `--name` rule.
