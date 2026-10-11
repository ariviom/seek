# Spec 0005 — Bundles: sharing an indexed Channel or Playlist

Status: ready-for-agent
New glossary term: Bundle (CONTEXT.md). New decision to record with the implementation: ADR 0007 (a Bundle is a
single SQLite file read as untrusted input). Ships, for hand-to-hand sharing, the content-carrying pack that
`docs/product/desktop-mvp.md` §4 deferred. Shaped by a grilling session on 2026-10-11.

## Problem Statement

Indexing a Channel is the slow part of Seek. Fetching a few hundred Transcripts takes hours at the pace YouTube
allows, and embedding them takes longer still on a laptop without a GPU. When I've already indexed a Channel or a
Playlist and a friend wants to consult it too, the only thing I can hand them is my whole `seek.db`, with every other
Channel, my Groups, and my Conversations in it. Otherwise they ingest it all again from scratch.

## Solution

I export one Channel or one Playlist to a **Bundle**: a single `.seek` file holding its indexed Videos with their
Transcripts, Segments, and vectors. I hand the file over however I like. My friend runs one command to import it and
has the same Channel or Playlist in their Library straight away: searchable, citable, and ready to chat with, with
nothing fetched from YouTube and nothing embedded. From then on it is an ordinary Library entry. Their next Sync picks
up only what has been published since.

## User Stories

### Exporting
1. As a learner, I want to export one Channel to a file, so that I can share its index without sharing my whole knowledge base.
2. As a learner, I want to export one Playlist to a file, so that a curated set of Videos from many creators travels as one thing.
3. As a learner, I want to name the Channel or Playlist the way `seek sync` lets me, by its name or its YouTube id, so that I don't learn a second way of pointing at it.
4. As a learner, I want the file to end in `.seek`, so that it's clear what it is and what opens it.
5. As a learner, I want the Bundle to hold only the Videos that are searchable in that Channel or Playlist, so that excluded and failed Videos don't travel.
6. As a learner, I want a Channel's Bundle to carry its date-range and most-recent filters, so that my friend's first Sync doesn't ingest everything I deliberately left out.
7. As a learner, I want my Groups, Conversations, settings, and other Channels left out, so that sharing one Channel shares nothing else.
8. As a learner, I want to export while the server is running, even during a Sync, so that I don't have to stop anything.
9. As a learner, I want to export a Paused Channel or Playlist, so that pausing something doesn't stop me sharing it.
10. As a learner, I want export to refuse to overwrite a file that already exists, so that I never lose a Bundle by retyping a path.
11. As a learner, I want an interrupted export to leave no half-written `.seek` file, so that I never hand over a broken Bundle.
12. As a learner, I want export to tell me how many Videos and Segments went in and how big the file is, so that I know what I'm about to send.
13. As a learner, I want export to refuse when the Channel or Playlist has no indexed Videos, so that I don't share an empty file.
14. As a learner, I want export to finish without loading the embedding model, so that it takes seconds, not a model load.
15. As a learner, I want to be reminded that a Bundle carries creators' full Transcripts, so that I decide who to share it with knowingly.

### Importing
16. As a friend, I want to import a Bundle with one command, so that I have the Channel or Playlist without ingesting it.
17. As a friend, I want the imported Videos to be searchable and citable at once, so that the import is the whole wait.
18. As a friend, I want to import before I've added anything, or even before I've first started the server, so that a Bundle can be my first Channel.
19. As a friend, I want the imported Channel or Playlist to be an ordinary Library entry, so that I can rename it, Pause it, put the Channel in a Group, chat with it, and delete it like any other.
20. As a friend, I want my next Sync to fetch only the Videos published since the Bundle was made, so that the saved work stays saved.
21. As a friend, I want a Channel's filters to arrive with it, so that my Library matches what was shared until I change it.
22. As a friend, I want a Playlist's Videos credited to their creators, with names and avatars, and those creators kept out of my Library, so that an imported Playlist behaves exactly like one I added.
23. As a friend, I want to choose the name the entry is added under, so that it reads the way I think of it.
24. As a friend, I want import to tell me how many Videos it added, how many I already had, and how many my own settings left out, so that I know what changed.
25. As a friend, I want import to say what to do next (start a Sync to pick up newer Videos), so that there's one obvious step.
26. As a friend, I want import to work without loading the embedding model, so that it runs on a machine that's slow at embedding.

### Merging with what I already have
27. As a learner, I want a Video I've already indexed left exactly as it is, so that an import never overwrites my own work.
28. As a learner, I want a Video I have but haven't finished indexing (still queued, mid-pipeline, or failed) to be completed from the Bundle, so that an import also unsticks what my own Syncs couldn't finish.
29. As a learner, I want importing a Channel I already have to keep my name, filters, Pause state, and check schedule, so that someone else's settings never replace mine.
30. As a learner, I want importing a newer Bundle of the same Channel or Playlist to add only what's new, so that a re-import is a cheap top-up.
31. As a learner, I want a creator I know only through a Playlist to come into my Library when I import their Channel's Bundle, keeping the Videos I already have, so that it works the way adding them would.
32. As a learner, I want a Bundle's Videos that are under my minimum length, or outside my existing Channel's date filters, left out, so that my rules hold on my machine.
33. As a learner, I want a Video in an imported Playlist to be searchable even where its Channel's filters would exclude it, so that inclusion wins for imported Playlists as it does for my own.

### Refusals
34. As a friend, I want a Bundle made with a different embedding model refused with a sentence naming both models, so that I never end up with vectors that can't be compared.
35. As a friend, I want a Bundle made by a newer Seek refused with "upgrade Seek", so that I know the fix.
36. As a friend, I want a file that isn't a Bundle refused plainly, so that a wrong path isn't a stack trace.
37. As a friend, I want a damaged or tampered Bundle refused before anything is written, so that a bad file can't leave my Library half-changed.
38. As a friend, I want a Playlist whose name I've already given another Playlist refused, pointing me at `--name`, so that names stay unambiguous.
39. As a friend, I want import refused while a Sync is running, with a sentence telling me to try again when it finishes, so that the two never write the same Videos at once.

### Robustness
40. As a friend, I want to import while the server is running, so that I don't have to stop it.
41. As a friend, I want an interrupted import to carry on where it stopped when I run it again, so that a closed laptop doesn't cost me the work.
42. As a friend, I want a Sync I queue during an import to wait and then run, so that nothing I asked for is lost.
43. As a friend, I want the text inside a Bundle treated as untrusted content the way a Transcript is, so that a Bundle from someone else can't instruct my chat model.
44. As a friend, I want import to remind me that a Bundle's text is only as trustworthy as whoever made it, so that I weigh its Citations accordingly.
45. As a friend, I want an avatar that doesn't come from YouTube dropped, so that opening my Library never calls a server the Bundle's maker chose.
46. As a learner, I want a Channel's Playlist filter left behind and to be told so, so that a playlist only I can see never breaks my friend's Syncs.

## Implementation Decisions

### The Bundle file
- A Bundle is one SQLite database with the extension `.seek`, in plain tables: no FTS5 index and no sqlite-vec
  table, so any SQLite can read it without extensions. It uses a rollback journal, not WAL, so it is always exactly
  one file.
- It carries Seek's own `application_id` in the SQLite header: a fixed 32-bit constant, the ASCII bytes of `SEEK`.
  Import uses it to tell a Bundle from any other SQLite file.
- Exactly one meta record holds: the Bundle format version (1), the Seek version that wrote it, the embedding
  model's name and dimension, the kind (Channel or Playlist), and when it was exported.
- A Bundle holds exactly one Library entry:
  - **Channel Bundle:** the Channel's YouTube channel id, name, avatar, and two of its filters: the date range
    and the most-recent count. Its Playlist filter does not travel. It names a YouTube playlist the recipient's
    every Sync would have to list, and one they can't see would fail each of them.
  - **Playlist Bundle:** the Playlist's YouTube playlist id and name, plus each creator its Videos are credited to
    (YouTube channel id, name, avatar), and each Video's position.
- Per Video: its YouTube id, its creator's YouTube channel id, title, duration, publish date, description,
  chapters, and language; its Transcript (source, language, cues, when fetched); and its Segments (start, end,
  text, chapter title, context, cues), each with its vector and an explicit ordinal giving its order in the Video.
- A Video may have no Segments: one whose captions are all blank reaches `done` that way, and it travels so the
  recipient's Sync doesn't fetch it again.
- Vectors are stored exactly as the knowledge base holds them: little-endian float32, `dimension × 4` bytes. No
  float16, no compression.
- Nothing identifies a row by a local id. Everything is keyed by YouTube ids, and Segments by their ordinal within
  the Video.
- Pause state, check schedule, Groups, Conversations, settings, Syncs, storyboards, excluded Videos, failed
  Videos, and Videos not yet `done` are not in a Bundle.

### Export
- `seek export --channel NAME_OR_ID FILE` and `seek export --playlist NAME_OR_ID FILE`. Exactly one of the two is
  required. They match a name or YouTube id the way `seek sync` does, including the message when a name matches
  more than one Channel, but always against the knowledge base in this process: export is never handed to the
  server. A Channel outside the Library is not found.
- Both commands open and migrate the knowledge base as the server does, with the embedding model and dimension
  from `Config`, so a knowledge base embedded with another model is refused exactly as the server refuses it. The
  Bundle's meta records the knowledge base's model and dimension.
- The path is used as given, with `.seek` added when it doesn't already end in it.
- The Bundle's Videos are the ones that are `done` and not excluded: those credited to the Channel, or those the
  Playlist includes. Pause state is ignored, so a Paused entry exports what it would search if Active.
- A Channel's Bundle includes Videos that are searchable only because one of the exporter's Playlists includes
  them. On the recipient's machine the Channel's filters will exclude those at the next Sync. This is accepted.
- Export reads the knowledge base in one read transaction, so the Bundle is a consistent snapshot even while a Sync
  writes. It takes no lease and runs beside the server.
- Vectors are read one lookup per Segment id. The vector table finds a row by its id but scans every vector for
  any other condition.
- It writes to a temporary name beside the destination and renames it into place when complete. It refuses when the
  destination exists, and when the entry has no Videos to export.
- It does not load the embedding model.
- It prints the entry's name, the number of Videos and Segments, the file's size, and one line saying the file
  contains the creators' Transcripts. For a Channel with a Playlist filter, it adds that the filter was left out,
  so the recipient's Syncs will bring in the Channel's other Videos.

### Import
- `seek import FILE [--name NAME]`. It runs in the CLI's own process against the knowledge base, whether or not the
  server is running, and creates the knowledge base if it doesn't exist yet (see Export for how both commands open
  it). It does not load the embedding model.
- **The Bundle is untrusted input.** It is opened read-only on its own connection, with no extensions loaded and
  schema-embedded SQL untrusted. It is never attached to the knowledge base's connection. Import reads only the
  expected tables and columns, and copies values through Python. Any SQLite error on that connection (not a
  database, a missing table, a virtual table it can't open) is the plain "not a Bundle" refusal, never a traceback.
- **Validation runs over the whole Bundle before anything is written.** Any violation refuses the import with a
  message and leaves the knowledge base untouched. It checks:
  - the `application_id`, exactly one meta record, a format version this build knows (a newer one says to upgrade
    Seek), and the kind;
  - the embedding model's name and dimension against the knowledge base's, naming both in the refusal;
  - YouTube ids against the pattern the web API already accepts for a playlist id (1 to 64 characters of letters,
    digits, `_`, and `-`), each Video and each creator appearing once;
  - names and titles: non-empty text of bounded length with no control characters;
  - publish dates as ISO dates and timestamps as ISO timestamps, since listings parse them;
  - chapters, Transcript cues (start, end, text), and Segment cues (start, offset) each as the shape Seek stores.
    The two cue shapes differ;
  - a Transcript source and language a Sync would have accepted (English only today);
  - a Channel's filters within the ranges the web API accepts;
  - that every Video has a Transcript, its Segments' ordinals run without gaps, and every Segment has a vector of
    exactly `dimension × 4` bytes whose values are all finite. No Segments is valid;
  - that a Channel Bundle's Videos are all credited to its Channel, and a Playlist Bundle's Videos are each
    credited to a creator the Bundle lists.
- An avatar is kept only when it is an `https` URL on one of YouTube's avatar hosts. Any other is dropped, not
  refused: the entry shows initials until a Sync's listing supplies one.
- **The lease.** Import takes the Sync lease before writing and renews it from a background thread at the worker's
  cadence (a quarter of the lease's length). If a Sync holds the lease, import refuses and says to run it again
  when the Sync has finished. If a renewal fails, import stops before its next Video, as the worker does, and says
  to run it again. Syncs queued meanwhile wait and run once import releases the lease.
- **The entry**, in one transaction:
  - A Channel not known is created in the Library, Active and checked daily, under the Bundle's name (or `--name`),
    with the Bundle's avatar and filters.
  - A Channel known only outside the Library is brought into it the same way, keeping its Videos. Bringing it in
    resets its filters, so the Bundle's are applied afterwards.
  - A Channel already in the Library keeps its name, filters, Pause state, check schedule, and avatar.
  - A Playlist not known is created, Active and checked daily, under the Bundle's name (or `--name`). If another
    Playlist has that name, import refuses and points at `--name`.
  - A Playlist already added keeps its name and settings.
  - Channel names are not unique in Seek today, so an imported Channel may share a name with another, as one added
    in the web UI may.
  - `--name` applies only when the entry is created. When the entry already exists, import says it kept the
    existing name.
- **Each Video**, in a transaction of its own:
  - A Video already known keeps the Channel it is credited to, in both kinds of Bundle. A Channel Bundle's Video
    that is credited here to a different Channel is left untouched and reported.
  - **Playlist Bundle.** The Playlist is made to include the Video at the Bundle's position (the next Sync settles
    the order). A Video not yet known is credited to its creator, and a creator not yet known becomes a Channel
    outside the Library. The Video is then judged exactly as a Playlist Sync's discovery judges one it includes:
    only the minimum length can exclude it, and any exclusion by its Channel's filters is lifted.
  - **Channel Bundle, Video not yet known.** It is judged by the minimum length and the date-range filters in
    force on the Channel after the entry step. One they exclude is not added; the next Sync discovers it as usual.
    The Playlist filter and most-recent count need a listing, so the next Sync applies them.
  - **Channel Bundle, Video already known.** Its exclusion is not judged again. One that is excluded stays excluded
    and untouched, since the recipient's own Sync judged it with every filter. One that a Playlist of the
    recipient's includes is not excluded by filters in the first place, so inclusion still wins.
  - After that, a Video that is excluded is not filled in, and a Video already `done` is left untouched.
  - Any other Video takes its details, Transcript, Segments, and vectors from the Bundle, replacing whatever it
    had, clears any recorded failure, and becomes `done`. The Bundle's Segment rows are inserted as they are, in
    ordinal order, and each vector is filed under the id its Segment was given. The Transcript is never re-cut:
    the recipient's segmenter could produce a different number of Segments than the vectors were made for. The
    existing triggers keep the lexical index in step.
- **Resuming.** Import keeps no progress record. Running it again repeats the merge, and Videos already `done` are
  skipped, which is the resume.
- **Progress.** The import function takes a callback it calls after each Video is committed. The CLI prints
  progress with it; it is also how a test holds an import open or stops it partway.
- **Afterwards.** Imported Videos are searchable at once. As with a newly added entry, automatic checks begin only
  after the first Sync, which is the recipient's to start. That Sync lists the whole Channel or playlist, finds the
  imported Videos `done`, and ingests only what is new. A private playlist the recipient can't list fails that
  Sync with the existing message and removes nothing; an empty listing is already refused the same way.
- Import prints the entry's name, any filters that arrived with a new Channel, and a count for each outcome, every
  Video in the Bundle falling in exactly one:
  - **added:** became `done` from the Bundle, whether new or completed from an unfinished or failed state;
  - **already indexed:** was `done` and untouched;
  - **left out:** excluded by the recipient's rules, or credited here to another Channel, with a count per reason.
- It then prints that the text came from whoever made the file, and the next step.
- A running server is not told about the import. Its pages show the new entry on their next load.

### CLI
- `export` and `import` join the existing subcommands, with help text in the same voice.
- Refusals exit non-zero with one sentence prefixed `seek:`, like the other commands.
- `seek list` and `seek status` need no change: an imported entry is an ordinary one, shown as never synced.

### Schema
- The knowledge base's schema does not change, and there is no migration. The Bundle has its own format version,
  independent of the knowledge base's schema version.

### Docs
- README: a "Sharing a Channel or Playlist" section with both commands, what a Bundle holds and leaves out, a rough
  size guide (about 4 KB of vectors per Segment, so on the order of 100 MB for a Channel of 900 Videos), the
  embedding-model requirement, and the note that a Bundle redistributes creators' Transcripts. It also says that a
  Bundle is only as trustworthy as whoever made it, and that a Channel's Playlist filter does not travel.
- HANDOFF mentions Bundles. The glossary entry is already written.
- ADR 0007 records the format decision: a single SQLite file read as untrusted input, over a zip of JSON lines
  with a vector array (safer to parse, more code, two formats to keep in step). It also records two things
  accepted with it. A Bundle is unsigned, so a hostile one can put invented text under a real Video's id and its
  Citations will point at real footage. And import is the first command that writes beside a running server, which
  ADR 0002 named as a reason to revisit; the Sync lease and the busy timeout are the answer.

## Testing Decisions

- Tests exercise external behaviour. They call the export and import command functions with a `Config`, as the
  sync-command tests call theirs, and assert what a user sees through the app's own surfaces: the entry listed over
  HTTP, search results and their Citations, MCP tool results, Sync outcomes, and the command's report or refusal
  message. They do not assert table contents of the knowledge base or of the Bundle, except where "nothing was
  written" is itself the behaviour.
- **One seam: the two command functions, observed through the app.** A test builds a Library through the app with
  the fake source and fake embedder, Syncs it, exports, then imports into a second `Config` with its own data
  directory and asserts through an app started on that directory. Both `Config`s carry the fake embedder's model
  name and dimension, since the commands open the knowledge base with `Config`'s. The fixtures' YouTube ids
  (`UC-wright`, `v-wright`, `PL-picks`) satisfy the id pattern. Covered here:
  - A Channel round trip: listed, searchable by both a lexical and a vector match, Citations at the right
    timestamps, the date range and most-recent count carried, a Playlist filter not carried and export saying so.
  - A Playlist round trip: creators credited with names and avatars, creators outside the Library, positions kept,
    the Playlist usable as a search scope.
  - The following Sync fetches no Transcript for an imported Video and ingests only a newer one (the fake source
    records what was fetched).
  - Excluded and failed Videos are not in the Bundle; a Paused entry still exports; a `done` Video with blank
    captions and no Segments round-trips and is not fetched again.
  - Merging: a Video already `done` is untouched; an unfinished or failed one is completed; an existing Channel
    keeps its name and filters; a re-import of a larger Bundle adds only the new Videos; a creator outside the
    Library is brought in with its Videos and the Bundle's filters.
  - The recipient's rules: a Video under the minimum length is left out; a new Video outside an existing Channel's
    date filter is left out; a known Video excluded by a most-recent count stays excluded; inclusion wins for a
    Playlist Bundle; and a Channel Bundle completes an unfinished Video that one of the recipient's Playlists
    includes, whatever the Channel's filters.
  - The report's three counts for a Bundle that produces all three.
  - Import into a data directory that has never been started.
  - Import beside a running server: search on the server finds the imported Segment. With the import held open by
    its progress callback, a Sync queued on the server waits, then runs once the import ends. The app is given a
    short Sync poll interval, since the worker finds a released lease by polling.
  - Import refuses while a Sync holds the lease (a `Gate` holds the Sync open).
  - An import stopped partway by its progress callback, run again, ends with every Video searchable once.
  - Export refuses an existing destination and an entry with no indexed Videos, and leaves no file behind when it
    fails.
- **Refusals from hand-built files**, through the same import function. Each file is built with `sqlite3` in the
  test: not a SQLite file, a SQLite file without the `application_id`, a newer format version, a different
  embedding model or dimension, a vector of the wrong length, a non-finite vector value, a Segment without a
  vector, a gap in a Video's Segment ordinals, malformed Transcript cues, malformed Segment cues, a publish date
  that isn't a date, a Video listed twice, a Transcript in another language, a Video credited to a creator the
  Bundle doesn't list, a Bundle that declares a virtual table, and a Playlist name already taken. Each asserts the
  message and that the Library is unchanged. One more file carries an avatar on another host and imports with the
  avatar dropped.
- **CLI parsing**, in the CLI lifecycle test pattern: exactly one of `--channel` and `--playlist`, the `.seek`
  suffix, and a refusal exiting non-zero with the `seek:` sentence.
- Prior art: the sync-command, CLI lifecycle, status-command, playlists, playlist-inclusion, keep-rule, and search
  test modules, and the harness helpers (`running`, `serving`, `Gate`, `fetched`, `add_channel`, `add_playlist`).
- No migration test, since the schema does not change. The retrieval baseline is unaffected.

## Out of Scope

- A visible file icon for `.seek` files. It needs an installed app to register the type, which is the Tauri
  shell's job (MVP §6).
- Export or import from the web UI, and telling a running server's pages about an import as it happens.
- Exporting a Group, several entries in one Bundle, or the whole Library.
- Importing a Bundle made with a different embedding model by re-embedding its Transcripts.
- Hosting, discovery, or in-app download of Bundles, and the `publisher` and `signature` fields MVP §4 reserved.
- Creator consent tooling. Sharing a Bundle is the sharer's decision.
- Tracking the segmentation shape a Bundle was cut with (`segmenter_version` in MVP §4).
- Smaller vectors (float16) or a compressed Bundle.
- Storyboards in a Bundle. Their URLs expire; the recipient backfills them.
- Group recipes (MVP §4's JSON export of sources without content), which remain a separate feature.

## Further Notes

- MVP §4 reserved a content-carrying pack format and said shipping it waits for creator consent tooling. A Bundle
  is that pack, shipped early for handing a file to a friend. It keeps the reserved `format_version`,
  `embedding_model`, and `embedding_dimension`; the format version leaves room for the rest.
- If the passage shape changes after a Bundle was made, the recipient runs `seek reindex` on the imported entry.
  It re-segments and re-embeds from the Transcripts the Bundle carried, without fetching.
- A Channel exported with a Playlist filter arrives without it, so the recipient's first Sync ingests the
  Channel's Videos outside that playlist, within the date range and most-recent count that did travel. The
  recipient can set a Playlist filter of their own before that Sync.
- A Channel with a most-recent filter can lose older imported Videos at the recipient's first Sync, if the Channel
  has published since the export. That is the filter working as it does on the exporter's machine.
- Sizes from the reference Library on 2026-10-11: 3,679 Videos and 64,637 Segments. Its largest Channel has 915
  Videos and 23,919 Segments, about 98 MB of vectors before text.
