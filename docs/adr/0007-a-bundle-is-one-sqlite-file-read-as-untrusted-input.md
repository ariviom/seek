# 0007 — A Bundle is a single SQLite file, read as untrusted input

Status: accepted, 2026-10-11

## Context
Indexing a Channel takes hours of fetching and embedding, and the only thing that could be handed to a friend was the
whole `seek.db`. Spec 0005 adds the **Bundle**: one Channel's or one Playlist's indexed Videos in a `.seek` file,
exported from one Library and imported into another. It is the content-carrying pack `docs/product/desktop-mvp.md` §4
reserved, shipped early for hand-to-hand sharing, so the file comes from someone else and import has to treat it so.

## Decision
A Bundle is one SQLite database in plain tables: no FTS5 index and no sqlite-vec table, a rollback journal, Seek's
`application_id` in the header, one meta record (format version 1, embedding model and dimension, kind), and nothing
keyed by a local id. Vectors are the knowledge base's own bytes.

Import reads it as untrusted input. The file is opened read-only on a connection of its own, never attached to the
knowledge base's, with no extension loaded and `trusted_schema` off. Every table it reads must be an ordinary table.
The whole Bundle is checked, inside one read transaction, before the knowledge base is opened: anything a Sync or the
web API could not have stored is a refusal, and the JSON columns are parsed strictly and written back in Seek's own
serialisation. Avatars are kept only on YouTube's avatar hosts.

## Considered Options
- **A zip of JSON lines with a vector array.** Safer to parse, since nothing in it is a schema that can carry SQL. But
  it is more code, and a second format to keep in step with the knowledge base's own tables. The SQLite surface is
  closed instead by the read-only connection, the plain-table check, and copying values through Python.

## Consequences
- Export is a copy between two SQLite files in one read transaction, and any SQLite can read a Bundle.
- **A Bundle is unsigned**, which is accepted for handing a file to a friend; MVP §4's `publisher` and `signature`
  stay reserved. Validation holds a Bundle to the shape of what a Sync stores, not to the truth. So a hostile Bundle
  can:
  - put invented text under a real Video's id, and its Citations will point at real footage;
  - carry any characters a Transcript from YouTube could, invisible ones included, into a model's context. Import
    filters none out; the untrusted-content framing every model already gets is the defence;
  - make a Segment rank for words it never shows, since a Segment's context (in the lexical index beside its text)
    and its vector are taken as given. Checking either would mean embedding the Bundle again;
  - fill in the unfinished Videos of a Channel the user added themselves. A Playlist Bundle fills one in under
    whichever Channel the Video is credited to here, whatever creator the Bundle claims, so its text can land under
    a Channel it never named;
  - bring a creator known only through a Playlist into the Library under the Bundle's name, avatar, and filters;
  - make a Video it lists in a Playlist searchable where the recipient's Channel filters had excluded it, as adding
    the playlist would. The minimum length still holds.

  What holds regardless: a Video that is `done` is never touched, and a Channel already in the Library keeps its
  name, avatar, and settings (a Playlist Bundle changes no Channel already known at all).
- **Import is the first command to write beside a running server**, which ADR 0002 named as a reason to revisit the
  single-file store. The answer is the Sync lease and the busy timeout, not a new store. Import takes the lease after
  the whole Bundle is validated and before its first write, renews it from a background thread at the worker's
  cadence and again before each Video, and releases it however it ends. Each Video is one transaction, so the
  server's writes wait for one Video at most. The lease keeps a Sync and an import apart; it does not cover the
  server's other writes (adding or deleting a Channel, a chat), which interleave between Videos as they do with a
  Sync.
- A Bundle imports only into a knowledge base with the same embedding model, and its Transcripts are never re-cut:
  the Segments arrive as they were, since the vectors were made for them. `seek reindex` re-cuts from the Transcripts
  it carried if the passage shape changes.
- Export does not apply import's checks. A Channel whose name holds a bidi override exports a Bundle that import
  refuses; the sender renames it and exports again.
