# 06: Document Bundles

**What to build:** Someone reading the README can share a Channel or Playlist and import one without asking me how, knows what a Bundle holds and what sharing one means, and the format decision is on record. See Spec 0005 §Docs.

**Blocked by:** 02, 03, 04, 05.

**Status:** ready-for-agent

- [ ] The README has a "Sharing a Channel or Playlist" section with both commands and `--name`, what a Bundle holds and leaves out, and the next step after an import (start a Sync).
- [ ] It gives a rough size guide: about 4 KB of vectors per Segment, on the order of 100 MB for a Channel of 900 Videos.
- [ ] It says a Bundle only imports into a knowledge base using the same embedding model.
- [ ] It says a Bundle redistributes creators' Transcripts, that a Bundle is only as trustworthy as whoever made it, and that a Channel's Playlist filter does not travel.
- [ ] The README's CLI summary lists `seek export` and `seek import`.
- [ ] HANDOFF mentions Bundles.
- [ ] ADR 0007 records the format decision: a single SQLite file read as untrusted input, over a zip of JSON lines with a vector array. It records as accepted that a Bundle is unsigned, so a hostile one can put invented text under a real Video's id; and that import is the first command to write beside a running server, which the Sync lease and the busy timeout answer (ADR 0002).
- [ ] The docs describe the behaviour as it landed in tickets 01 to 05, including any reading recorded in their comments.
