# 02: Refuse a damaged or hostile Bundle

**What to build:** A Bundle from someone else is untrusted input. When I import one that is damaged or tampered with, import refuses it with one plain sentence before anything is written, so my Library is never left half-changed. It can't make my Library call a server its maker chose, and import reminds me that its text is only as trustworthy as whoever made it. See Spec 0005 §Import ("The Bundle is untrusted input", "Validation runs over the whole Bundle").

**Blocked by:** 01 (Share a Channel with someone who doesn't have it).

**Status:** ready-for-agent

- [ ] Validation runs over the whole Bundle before the first write. Any violation refuses the import and leaves the knowledge base untouched.
- [ ] YouTube ids must match the pattern the web API already accepts for a playlist id, and each Video and each creator appears once.
- [ ] Names and titles are non-empty text of bounded length with no control characters.
- [ ] Publish dates parse as ISO dates and timestamps as ISO timestamps. Chapters, Transcript cues (start, end, text), and Segment cues (start, offset) each parse as the shape Seek stores.
- [ ] A Transcript's source and language are ones a Sync would have accepted. A Channel's filters are within the ranges the web API accepts.
- [ ] Every Video has a Transcript, its Segments' ordinals run without gaps, and every Segment has a vector of exactly `dimension × 4` bytes whose values are all finite. A Video with no Segments is valid.
- [ ] A Channel Bundle's Videos are all credited to its Channel.
- [ ] Any SQLite error while reading the Bundle, including a missing table and a declared virtual table, is the plain "not a Bundle" refusal and never a traceback.
- [ ] An avatar is kept only when it is an `https` URL on one of YouTube's avatar hosts. Any other is dropped, not refused, and the Channel shows initials.
- [ ] A successful import prints that the Bundle's text came from whoever made the file.
- [ ] Tests build each bad file with `sqlite3` and feed it through the import function: a wrong-length vector, a non-finite value, a Segment without a vector, a gap in the ordinals, malformed Transcript cues, malformed Segment cues, a publish date that isn't a date, a Video listed twice, a Transcript in another language, a Video credited to another creator, a second meta record, and a declared virtual table. Each asserts the message and that the Library is unchanged. One more file carries an avatar on another host and imports with it dropped.

## Comments

**2026-10-11, from the commit security review of ticket 01.** Import as it stands after 01 trusts the file, so it must not be merged or used on a Bundle from someone else until this ticket lands. The review named five ways that shows, each already a checkbox above:
- Ids, names, dates, cues, and vectors go into the knowledge base as given. Malformed chapters, cues, or a publish date that isn't a date arrive `done`, and then break every search and listing that reads them until the Channel is deleted.
- A Bundle's YouTube video and channel ids are later put into the URLs a Sync asks yt-dlp for. The id pattern closes that.
- A row the knowledge base rejects stops the import partway with a traceback, leaving the Channel and the Videos before it, and 01's known-Channel refusal then blocks a second try. Validation before the first write closes that.
- The avatar URL is stored and then loaded by the Library page from whatever server it names.
- `format_import` prints the Bundle's Channel name and puts its YouTube channel id in a command to copy (`seek sync --channel ID`). The id pattern and the ban on control characters make both safe to print; check the refusal messages that quote a name as well.
