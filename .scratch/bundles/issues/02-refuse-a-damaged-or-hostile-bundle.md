# 02: Refuse a damaged or hostile Bundle

**What to build:** A Bundle from someone else is untrusted input. When I import one that is damaged or tampered with, import refuses it with one plain sentence before anything is written, so my Library is never left half-changed. It can't make my Library call a server its maker chose, and import reminds me that its text is only as trustworthy as whoever made it. See Spec 0005 §Import ("The Bundle is untrusted input", "Validation runs over the whole Bundle").

**Blocked by:** 01 (Share a Channel with someone who doesn't have it).

**Status:** done

- [x] Validation runs over the whole Bundle before the first write. Any violation refuses the import and leaves the knowledge base untouched.
- [x] YouTube ids must match the pattern the web API already accepts for a playlist id, and each Video and each creator appears once.
- [x] Names and titles are non-empty text of bounded length with no control characters.
- [x] Publish dates parse as ISO dates and timestamps as ISO timestamps. Chapters, Transcript cues (start, end, text), and Segment cues (start, offset) each parse as the shape Seek stores.
- [x] A Transcript's source and language are ones a Sync would have accepted. A Channel's filters are within the ranges the web API accepts.
- [x] Every Video has a Transcript, its Segments' ordinals run without gaps, and every Segment has a vector of exactly `dimension × 4` bytes whose values are all finite. A Video with no Segments is valid.
- [x] A Channel Bundle's Videos are all credited to its Channel.
- [x] Any SQLite error while reading the Bundle, including a missing table and a declared virtual table, is the plain "not a Bundle" refusal and never a traceback.
- [x] An avatar is kept only when it is an `https` URL on one of YouTube's avatar hosts. Any other is dropped, not refused, and the Channel shows initials.
- [x] A successful import prints that the Bundle's text came from whoever made the file.
- [x] Tests build each bad file with `sqlite3` and feed it through the import function: a wrong-length vector, a non-finite value, a Segment without a vector, a gap in the ordinals, malformed Transcript cues, malformed Segment cues, a publish date that isn't a date, a Video listed twice, a Transcript in another language, a Video credited to another creator, a second meta record, and a declared virtual table. Each asserts the message and that the Library is unchanged. One more file carries an avatar on another host and imports with it dropped.

## Comments

**2026-10-11, from the commit security review of ticket 01.** Import as it stands after 01 trusts the file, so it must not be merged or used on a Bundle from someone else until this ticket lands. The review named five ways that shows, each already a checkbox above:
- Ids, names, dates, cues, and vectors go into the knowledge base as given. Malformed chapters, cues, or a publish date that isn't a date arrive `done`, and then break every search and listing that reads them until the Channel is deleted.
- A Bundle's YouTube video and channel ids are later put into the URLs a Sync asks yt-dlp for. The id pattern closes that.
- A row the knowledge base rejects stops the import partway with a traceback, leaving the Channel and the Videos before it, and 01's known-Channel refusal then blocks a second try. Validation before the first write closes that.
- The avatar URL is stored and then loaded by the Library page from whatever server it names.
- `format_import` prints the Bundle's Channel name and puts its YouTube channel id in a command to copy (`seek sync --channel ID`). The id pattern and the ban on control characters make both safe to print; check the refusal messages that quote a name as well.

**2026-10-11, implemented.** `import_bundle` now reads the whole Bundle and checks it before it opens the knowledge base: `_meta`, `_channel`, `_videos`, then `_contents` for every Video. `_contents` is what the write loop calls again, so nothing is written that the same code did not check. Tests are the seven from `test_import_refuses_a_bundle_whose_segments_or_vectors_are_damaged…` to the end of `tests/test_bundles.py`, each file made from a sound export with `sqlite3` statements (`altered`, `unconstrained`).

Two refusals, both one sentence: `FILE is not a Seek Bundle` (anything SQLite cannot read, the meta record, the kind, tables that are not plain) and `FILE is damaged or has been altered: WHAT` (everything about the Channel, a Video, a Transcript, or a Segment). A Video is named by its YouTube id once that id has passed the pattern, and nothing else from the file is ever quoted.

Readings taken:
- **Plain tables only.** The five tables import reads must each be an ordinary table (`PRAGMA table_list`). A virtual table SQLite can open, FTS5 for one, imported without a word before this check, and a view could run its maker's SQL for as long as they liked. Tables and columns import does not read are ignored, as are a Transcript or Segments of a Video the Bundle does not list. `exported_at` and `seek_version` are not read, so not checked.
- **One read transaction on the Bundle** for the whole import, so the second reading is of what the first one checked. Not pinned by a test, since no seam reaches between the two; checked by hand that a second SQLite connection's write is held off until import closes the file.
- **Not a Bundle, rather than damaged:** a kind other than `channel` (04 adds `playlist`), and an embedding model's name or dimension that is not fit to print, since the model refusal quotes both.
- **A `done` Video's fields are all required:** a length that is a whole number of seconds, a publish date written `YYYY-MM-DD` and nothing looser (listings sort it as text), a description, chapters, and `en` as its language. The reference Library's 2,877 `done` Videos have every one. A Transcript's fetch time is anything `datetime.fromisoformat` reads.
- **The JSON columns are parsed strictly and written back in Seek's own serialisation**, not copied byte for byte: chapters, Transcript cues, and Segment cues. A key too many, a number as text, `NaN`, or nesting deep enough to break a parser is a refusal; a sound file's `0` may arrive as `0.0`. A Segment must have at least one cue and each offset must fall inside its text: search raises on a Segment with none.
- **The rule for text:** a Bundle that `seek export` writes from a Library a Sync built must always import, so no check refuses what a Sync or the web API can store in that field. A Bundle's maker has the standing a Transcript's has; the defence against its text is the untrusted-content framing every model already gets, not a character filter.
- **Names and titles.** The Channel's name, the model's name, and a Video's title are at most 200 characters, with no control characters (C0, C1, U+2028, U+2029) and something visible in them, as the ticket asks. This is the one check that could in principle refuse what a Sync stored: yt-dlp hands a title over as YouTube gave it and Seek stores it as it comes, so it rests on YouTube keeping titles to a line. None of the reference Library's 3,679 titles holds one, the longest is 100 characters, and the longest Channel name is 36.
- **A name import prints** (the Channel's, and the model's in its refusal) may also not hold a bidi embedding, override, or isolate, U+202A to U+202E and U+2066 to U+2069, which reorder the line it is printed on. Every other format character stays, so a name that joins an emoji with a zero-width joiner imports. A Video's title is not held to this: one title in the reference Library wraps a phone number in U+202A…U+202C as YouTube gave it, and import prints no title.
- **A description and a chapter's title** are text of at most 20,000 characters and nothing more. yt-dlp passes a description on untouched (138 in the reference Library carry carriage returns; the longest is 4,998 characters), and cuts chapter titles from its lines with `.+?`, which takes anything but a newline. A chapter's title may be empty, which is what a Sync stores when YouTube gives none. A Segment's chapter title and context are held to the same bound only.
- **What was said**, a Segment's text and each Transcript line, has that bound and no whitespace but a space: `parse_json3` has collapsed a caption's whitespace since the first YouTube adapter (`7c9dbb8`), and the segmenter collapses it again. Other control characters pass, as they would through a Sync. None of the reference Library's 72,521 Segments holds a control character or loose whitespace; the longest runs 2,641 characters (context 303, chapter title 264).
- **Avatars** are kept on a literal prefix, `https://yt3.ggpht.com/` or `https://yt3.googleusercontent.com/`, so no URL parser has to agree with the browser's. All nine avatars in the reference Library pass.
- **Filters** go through the web API's own `FiltersBody`, so the ranges cannot drift apart.
- Export does not apply these rules, so a Channel whose name holds a bidi override, as YouTube gave it or as its owner renamed it, exports a Bundle that import refuses. The sender renames the Channel and exports again.

Changed on purpose: `format_import`'s lines in `test_import_says_what_it_added_and_what_to_do_next_and_refuses_a_channel_already_known` gain the sentence that the Bundle's text came from whoever made the file, between the count and the next step.

Commit security review, on the checkpoints:
1. *Text only type-checked.* Fixed as far as the rule for text allows: every piece of text has a length bound, and what was said is held to one line. A first pass also refused control characters in descriptions and chapter titles; that was taken back, since a Sync stores them.
2. *Names that spoof the line they are printed on.* Fixed: a printed name may not hold a bidi embedding, override, or isolate, and a name or title must have a visible character. A first pass refused every format, private-use, and unassigned character; that was narrowed, since it refused a name with a joined emoji, a flag, or an emoji newer than this Python's Unicode tables.
3. *Invisible characters reach a model's context* (flagged at the text checks). Acknowledged and accepted, not filtered: a Sync stores the same characters from YouTube, and the framing every model gets is the defence.
4. *A Segment's `context` is not checked against its Video's title and chapter.* Acknowledged and accepted. A Sync can change a Video's title after its Segments were cut, so equality would refuse honest Bundles, and the spec inserts Segment rows as they are. The context is in the lexical index beside the text (`segments_fts` holds both) and feeds the reranker, so a hostile Bundle can make a Segment match words it never shows. It can do the same through the text itself, and its vectors already decide what its Segments rank for, which nothing short of embedding them again could check. It is part of the unsigned-Bundle risk the spec accepts.

For later tickets:
- 03: validation must stay ahead of `_open_knowledge_base` and the entry step. `_videos` returns the Videos by YouTube id, already in the form `_import_video` inserts; `_contents` returns a Video's Transcript and Segments the same way. `--name` is the user's own text, not the Bundle's.
- 04: see its comments.
- 05: take the lease after the validation pass, not before it. The Bundle's connection holds a read transaction until import ends, which is harmless to the knowledge base's own.
- 06: the README's trust paragraph can lean on the readings above; the line import prints is "The Bundle's text came from whoever made the file, and is only as trustworthy as they are."
