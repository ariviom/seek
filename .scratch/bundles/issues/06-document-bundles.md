# 06: Document Bundles

**What to build:** Someone reading the README can share a Channel or Playlist and import one without asking me how, knows what a Bundle holds and what sharing one means, and the format decision is on record. See Spec 0005 §Docs.

**Blocked by:** 02, 03, 04, 05.

**Status:** done

- [x] The README has a "Sharing a Channel or Playlist" section with both commands and `--name`, what a Bundle holds and leaves out, and the next step after an import (start a Sync).
- [x] It gives a rough size guide: about 4 KB of vectors per Segment, on the order of 100 MB for a Channel of 900 Videos.
- [x] It says a Bundle only imports into a knowledge base using the same embedding model.
- [x] It says a Bundle redistributes creators' Transcripts, that a Bundle is only as trustworthy as whoever made it, and that a Channel's Playlist filter does not travel.
- [x] The README's CLI summary lists `seek export` and `seek import`.
- [x] HANDOFF mentions Bundles.
- [x] ADR 0007 records the format decision: a single SQLite file read as untrusted input, over a zip of JSON lines with a vector array. It records as accepted that a Bundle is unsigned, so a hostile one can put invented text under a real Video's id; and that import is the first command to write beside a running server, which the Sync lease and the busy timeout answer (ADR 0002).
- [x] The docs describe the behaviour as it landed in tickets 01 to 05, including any reading recorded in their comments.

## Comments

**2026-10-11, from ticket 02's commit security review.** ADR 0007 should record two more things as accepted with an unsigned Bundle, both reasoned in ticket 02's comments. A Bundle's text reaches a model's context with whatever characters it holds, invisible ones included, as a Transcript fetched from YouTube does; the untrusted-content framing is the defence, and import filters no characters out of what a Sync could have stored. And a Segment's context and vector are taken as given, so a hostile Bundle can make a Segment rank for words it never shows; the context is in the lexical index beside the text, and checking either would mean embedding the Bundle again.

**2026-10-11, from ticket 03's commit security review.** ADR 0007 should record two more things as accepted with an unsigned Bundle, both the spec's own behaviour. Importing into a Channel already in the Library fills in its unfinished Videos from the Bundle, so a hostile Bundle can put its text under a Channel the user added themselves; a Video that is `done` is never touched. And a creator known only through a Playlist comes into the Library under the Bundle's name, avatar, and filters; a Channel already in the Library keeps all of its own.

**2026-10-11, from ticket 04's commit security review.** ADR 0007 should record two more things as accepted with an unsigned Bundle, both the spec's behaviour for a Playlist Bundle. It fills in an unfinished Video the Library already knows under whichever Channel the Video is credited to here, whatever creator the Bundle claims, so it can put its text under a Channel it never named; a `done` Video is never touched and no Channel already known is changed. And a Playlist Bundle that lists a Video makes it searchable where the recipient's Channel filters had excluded it, as adding the playlist would (inclusion wins); the minimum length still holds. The README should also show `seek export --playlist`, the Playlist form of the import report (ticket 04's comments), and that a name another Playlist has is refused pointing at `--name`.

**2026-10-11, from ticket 05.** The README should say: `seek import` runs with the server up or down; it is refused with "A Sync is running; run the import again when it has finished" while one is, including for up to 20 seconds after a server was killed mid-Sync; a Sync queued during an import waits and starts within the server's poll interval (5 seconds) of the import ending; an interrupted import is simply run again, and it keeps no progress record; progress is printed on stderr and the report on stdout; and the server's pages show the new entry on their next load, since it is not told. ADR 0007, on import being the first command to write beside a running server (ADR 0002): the answer is the Sync lease, taken after the whole Bundle is validated and before the first write, renewed by a background thread at the worker's cadence and again before each Video, and released however the import ends; plus one transaction per Video under the busy timeout, so the server's writes wait for one Video at most. The lease keeps a Sync and an import apart; it does not cover the server's other writes (adding or deleting a Channel, a chat), which interleave between Videos as they do with a Sync.

**2026-10-11, implemented.** Docs only. The README has "Sharing a Channel or Playlist" between "Check on it from the command line" and "Data", and a link to it naming both commands in the Contents' Reference line. `HANDOFF.md` has a dated Bundles entry after the Playlists one. The decision is `docs/adr/0007-a-bundle-is-one-sqlite-file-read-as-untrusted-input.md`, with every item the comments above asked for under its unsigned-Bundle and running-server consequences.

Readings taken:
- **The README has no CLI summary to add to.** Its commands are introduced section by section, so the two new ones are in the new section's code block and in the Contents line, which is the nearest thing to a list.
- **The docs follow the code where tickets 01 to 05 read the spec differently:** a new Channel's date range leaves Videos out at import, not at the next Sync (03); the report's first line always carries all three counts (03); a Playlist Bundle's `done` Video is not judged again (04); the lease is renewed before each Video as well as by the thread (05). The example report uses the default 120 second minimum.
- **Also said, from the tickets' readings:** a killed export can leave a `.tmp` file, and a Bundle is readable by its owner alone (01); a Channel whose name holds a bidi override exports a Bundle import refuses (02, in the ADR).
- **Left alone:** the README's "Channels and Playlists are added in the web UI; the command line only Syncs what the Library already has" is no longer the whole truth, since `seek import` adds an entry. The README has uncommitted edits from other work in another checkout, so this ticket kept to the new section and the Contents line, and that sentence was not touched.
