# Ticket 01 review — 2026-10-11

Fixed point: `e3872f6`. Independent Standards and Spec `reviewer` agents read the working-tree diff of `src` and `tests`, ticket 01, Spec 0005, the sibling tickets, CONTEXT.md, and HANDOFF's conventions, each asked for everything it found. The Spec agent also probed a scratch export by hand.

## Spec

Found and fixed:
- **Import crashed and left the Library half-changed when a Bundle's Video was already known under another Channel** (a friend's Playlist crediting it to another creator): the Channel was created, the Video's insert hit the UNIQUE constraint, and the re-run was refused. Import now refuses up front when it knows the Channel or any of the Videos, with nothing written.
- **Export replaced a destination that appeared during the write**, since a POSIX rename replaces silently. The destination is checked again just before the rename.
- **`seek export --channel X .` was a traceback.** A directory is refused with a sentence.
- **The embedding-model refusal created a knowledge base first** in a never-started data directory. The comparison now precedes opening it, and the test asserts the directory does not exist.
- Tests that could not fail: the export report's Transcripts line and size are now asserted against literals; import's own "knowledge base embedded with another model" refusal is covered; the beside-a-Sync test is named for what it pins (no lease needed), not for a snapshot it could not show.

Verified by probe, not pinned by a test: the read snapshot holds while a write commits mid-export; a failure or Ctrl+C mid-write leaves no file; the file carries the `SEEK` application id, a `delete` journal, plain tables, and float32 blobs of `dimension x 4` bytes; paths with `?`, `#`, `%`, spaces, and relative paths import.

Left, and recorded in the ticket's comments: `database is locked` after the busy timeout is a traceback, as in the other commands; `.SEEK` in capitals; a killed export's `.tmp` file; `kind` unchecked on import (02, 04); a `done` Video missing its Transcript or a vector is a `TypeError` on export.

All fourteen checkboxes met after the fixes.

## Commit security review

Fixed: export's temporary file had a guessable name (`NAME.seek.<pid>.tmp`) and was opened without exclusive creation, so in a directory others can write to a planted link would have had the Bundle written through it. It is made with `mkstemp` now.

Open until ticket 02, and recorded in its comments: import trusts the file's ids, names, dates, cues, vectors, and avatar URL, stops partway on a row the knowledge base rejects, and prints the Bundle's name and id. Import is not safe on a Bundle from someone else until 02 lands.

## Standards

Found and fixed:
- `cli.import_` caught only `SyncCommandError`, though `channels.create_channel` raises `Conflict`; it catches both, as `cli.sync` catches the store's errors.
- Positional slices tied each SELECT's column order to an INSERT's in another statement. Every copy now binds by name.
- `search` and `Synonyms` were copied from `test_search.py`; both moved to the harness.
- `import_bundle`'s docstring promised a resume the command refuses; it says what is true now.
- The "already has the Channel" message was wrong for a creator known only through a Playlist; it now says so.
- `_reading` renamed `_open_bundle`; the `(model, dimension)` tuple unpacked.

Left as judgement calls: `_new_bundle` takes the destination only to word its error; `ExportReport` and `format_export` use "export" as the command's name, parallel to `SyncReport`, though the glossary avoids it as a noun for the file; `Synonyms` overrides the fake embedder's `_embed`, as it did in `test_search.py`.

Clean: comment density and docstring voice, glossary terms, tests through the app's surfaces, mypy strict.
