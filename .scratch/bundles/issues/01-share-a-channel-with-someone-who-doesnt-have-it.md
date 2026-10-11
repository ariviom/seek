# 01: Share a Channel with someone who doesn't have it

**What to build:** I export one Channel to a `.seek` Bundle with `seek export --channel NAME_OR_ID FILE`, hand the file over, and my friend runs `seek import FILE`. The Channel is in their Library straight away: listed, searchable, and citable, with nothing fetched from YouTube and nothing embedded. Their next Sync fetches only Videos published since. This is the tracer bullet: the Bundle format, both commands, and the round trip into a Library that doesn't know the Channel. Merging with Videos the recipient already has is ticket 03, full validation of a hostile file is 02, Playlists are 04, and the lease is 05. See Spec 0005 §The Bundle file, §Export, §Import, §CLI.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] A Bundle is one SQLite file in plain tables, with a rollback journal, Seek's `application_id`, and exactly one meta record: format version 1, the Seek version, the embedding model's name and dimension, the kind, and when it was exported. Nothing in it is keyed by a local id; Segments carry an ordinal.
- [x] `seek export --channel NAME_OR_ID FILE` matches a name or YouTube channel id as `seek sync` does, including the message when a name matches more than one Channel, always against the knowledge base in this process. A Channel outside the Library is not found.
- [x] The Bundle holds the Channel's `done`, non-excluded Videos with their details, Transcripts, Segments, and exact float32 vectors, plus the Channel's name, avatar, date range, and most-recent count. A `done` Video with no Segments travels. A Paused Channel exports the same Videos.
- [x] The Channel's Playlist filter is left out, and export says so when the Channel has one.
- [x] Export adds `.seek` when the path lacks it, writes under a temporary name and renames into place, refuses an existing destination, refuses a Channel with no Videos to export, and leaves no file behind when it fails.
- [x] Export reads one consistent snapshot, takes no lease, runs beside the server and during a Sync, reads vectors one lookup per Segment id, and never loads the embedding model.
- [x] Export prints the Channel's name, the Video and Segment counts, the file's size, and the line saying the file contains the creators' Transcripts.
- [x] `seek import FILE` opens the Bundle read-only on its own connection, with no extensions loaded and schema-embedded SQL untrusted, never attached to the knowledge base. It refuses a file that isn't a Bundle, a newer format version ("upgrade Seek"), and a different embedding model or dimension (naming both), each with nothing written.
- [x] Both commands open and migrate the knowledge base as the server does, with the embedding model and dimension from `Config`. Import works on a data directory that has never been started.
- [x] Import creates the Channel in the Library, Active and checked daily, with the Bundle's name, avatar, date range, and most-recent count. Each Video is written in a transaction of its own and arrives `done`, with the Bundle's Segment rows inserted as they are and each vector filed under its Segment's new id. The Transcript is never re-cut.
- [x] After import the Channel is listed, a lexical match and a vector match both find an imported Segment, and Citations point at the right timestamps.
- [x] The following Sync fetches no Transcript for an imported Video and ingests only a newer one. `seek list` shows the imported Channel as never synced.
- [x] Import prints the Channel's name, how many Videos it added, and that the next step is to start a Sync. Refusals from either command exit non-zero with one `seek:` sentence.
- [x] Tests call the two command functions with a `Config` carrying the fake embedder's model name and dimension, and assert through an app started on the second data directory. CLI parsing follows the CLI lifecycle test pattern. No test asserts the Bundle's table contents.

## Comments

**2026-10-11, implemented.** `src/seek/bundles.py` holds the format, `export_channel`, `import_bundle`, and the two formatters the CLI prints; tests are `tests/test_bundles.py` and one round trip in `tests/test_cli_lifecycle.py`. Review: `../ticket-01-review.md`.

Readings taken:
- The Bundle's tables are `meta` (one row), `channel` (one row: YouTube channel id, name, avatar, date range, most-recent count), `videos`, `transcripts`, and `segments` (keyed by YouTube video id and `ordinal`, with the vector in `embedding`). A Playlist Bundle (04) adds its own entry tables beside these; the format version stays 1, since no Playlist Bundle exists yet.
- Import refuses, before writing, a Bundle whose Channel the knowledge base already has (in the Library or outside it) or any of whose Videos it has under another Channel. This stands in for merging until 03, and it means an import that dies partway can't be run again without deleting the Channel first.
- The embedding model is compared with `Config`'s before the knowledge base is opened, so a refused file creates no knowledge base in a data directory that has never been started. A knowledge base embedded with another model than `Config`'s is then refused by opening it as the server does.
- Export refuses a path that is a directory, and checks the destination again just before the rename, which on POSIX replaces a file without a word. A file created in the instant between that check and the rename is still replaced.
- Refusals are `SyncCommandError`, as the other commands raise.
- `channels.create_channel` takes `filters` and applies them in its own transaction, so the entry is written in one.
- `harness.search` and `harness.Synonyms` moved out of `test_search.py`.

Not pinned by a test, checked by hand in review: the export snapshot holding while a write commits mid-export, and the temporary file being removed when the write fails or is interrupted partway.

For later tickets:
- 02: import never reads `kind`; a Bundle with no `channel` row, a non-ISO date, or a Video without a Transcript is a traceback; the avatar is stored as given; opening read-only with `trusted_schema` off is the only hardening so far. Validation has to run before `_open_knowledge_base` and before the first write, where the known-Channel check sits now.
- 03: `_known` and its refusal go. `ImportReport.added` is the Bundle's Video count, and the minimum length is not judged at import, so the first Sync excludes a Video under it.
- 05: import takes no lease and has no progress callback. `cli.import_` also catches `Conflict`, for a Channel added on the server between the check and the insert.
- A killed export leaves `NAME.seek.<random>.tmp` beside the destination. `wright.SEEK` becomes `wright.SEEK.seek`.
- A Bundle is written readable by its owner alone (the temporary file is made with `mkstemp`), whatever the umask.
