# Spec 0006 — Bundles in the web UI

Status: ready-for-agent
Builds on Spec 0005 and ADR 0007, which gains a note with the implementation. No new glossary term. Ships the piece
Spec 0005 listed as out of scope: export and import from the web UI, and telling open pages about an import. Shaped
by a grilling session on 2026-10-11; its ten decisions are in `.scratch/bundles-web-ui/handoff.md` and are not
reopened here. What this spec settled beyond them is listed under Further Notes.

## Problem Statement

I can share a Channel or a Playlist as a Bundle, but only from a terminal on the machine Seek runs on. I use Seek in
the browser, often from another device through the published host. To export I have to open a shell there, name the
entry, pick a path, and then get the file off that machine. A friend who wants to import has to get the file onto
their Seek machine and run a command, and the page they have open doesn't show the new entry until they reload it.
The friends I'd hand a Bundle to are the ones least at home in a terminal.

## Solution

A Channel's page and a Playlist's page each get an **Export** button. It asks me to confirm, builds the Bundle, and
my browser downloads it as `<name>.seek`, on whichever device I'm using. The Add Channel and Add Playlist dialogs each
get a second path, **or import a `.seek` file**: I pick the file, Seek imports it, and the dialog shows what was
added, selects the new entry, and offers to start a Sync. Both work wherever the web UI does. A Bundle is the same
file either way, and it is held to the same rules as `seek export` and `seek import`.

## User Stories

### Exporting
1. As a learner, I want an Export button on a Channel's page, so that I can share its index without opening a terminal.
2. As a learner, I want the same button on a Playlist's page, so that a curated set of Videos is as easy to share.
3. As a learner, I want Export to sit with the entry's other actions and not in the Library's rows, so that a row stays one click that selects.
4. As a learner, I want a confirmation that names the entry and says how many indexed Videos will go into the file, so that I know what I'm about to share.
5. As a learner, I want to be told before I export that the file contains the creators' full Transcripts, so that I decide who gets it knowingly.
6. As a learner, I want to be told before I export a Channel with a Playlist filter that the filter is left out, so that I can warn my friend their Syncs will bring in the Channel's other Videos.
7. As a learner, I want the Bundle to arrive as an ordinary browser download named after the entry and ending in `.seek`, so that I find it in my downloads and know what it is.
8. As a learner, I want an entry whose name holds characters a file name can't to download under a sensible name anyway, so that an emoji or a slash in a name never breaks the download.
9. As a learner, I want the dialog to say "Building…" until the download starts, so that I know a large Channel is being worked on.
10. As a learner, I want Export disabled, with a tooltip saying why, on an entry with no indexed Videos, so that I'm not offered an empty file.
11. As a learner, I want to export a Paused entry, so that pausing something doesn't stop me sharing it.
12. As a learner, I want to export while a Sync is running, so that I don't have to wait for it.
13. As a learner, I want to export from another device through the published host, so that the file lands on the device I'm holding.
14. As a learner, I want a refused export to say why in the dialog, so that I'm not left with a button that did nothing.
15. As a learner, I want nothing of an export left on the server's disk once I have the file, so that copies of Transcripts don't pile up there.

### Importing
16. As a friend, I want "or import a `.seek` file" in the Add Channel dialog, so that a Bundle is one of the ways to add a Channel.
17. As a friend, I want the same in the Add Playlist dialog, so that I find it wherever I went to add something.
18. As a friend, I want either dialog to take either kind of Bundle and tell me which arrived, so that I don't need to know what kind of file I was handed.
19. As a friend, I want to see the file's name and size before I press Import, so that I don't import the wrong file.
20. As a friend, I want the entry to take the Bundle's name without being asked, so that importing is one step; I can rename it on its page.
21. As a friend, I want the dialog to say "Importing…" while it works, so that I know to wait.
22. As a friend, I want a report of how many Videos were added, how many I already had, and how many were left out and why, so that I know what changed.
23. As a friend, I want the report to say when the entry was already in my Library and kept its name and settings, so that I'm not surprised the Bundle's name didn't appear.
24. As a friend, I want the report to say which filters arrived with a new Channel, so that I know what my next Sync will keep.
25. As a friend, I want to be reminded that a Bundle's text is only as trustworthy as whoever made it, so that I weigh its Citations accordingly.
26. As a friend, I want a "Start a Sync" button in the report, so that picking up newer Videos is one click.
27. As a friend, I want the imported entry selected in my Library when the report appears, so that I'm looking at what I just added.
28. As a friend, I want the imported Videos searchable as soon as the report appears, so that the import is the whole wait.
29. As a friend, I want a Bundle to be the first thing I add to an empty Library, so that I can start without ingesting anything.
30. As a friend, I want to import from another device through the published host, so that the file needn't be on the machine Seek runs on.
31. As a friend, I want an import whose file has fully arrived to finish even if I close the tab, so that a closed laptop lid doesn't leave it half done.

### Refusals
32. As a friend, I want the import option disabled while a Sync is running or queued, with the reason beside it, so that I don't upload a large file only to be refused.
33. As a friend, I want the server to refuse on its own if a Sync starts in between, so that the two never write the same Videos at once.
34. As a friend, I want a file that isn't a Bundle refused in plain words, so that a wrong pick isn't an error code.
35. As a friend, I want a refusal to call it "the file", never a path on the server, so that the sentence is about what I picked.
36. As a friend, I want a Bundle made with a different embedding model refused with a sentence naming both models, so that I know it can't be used here.
37. As a friend, I want a Bundle made by a newer Seek refused with "upgrade Seek", so that I know the fix.
38. As a friend, I want a damaged or altered Bundle refused before anything is written, so that a bad file can't leave my Library half changed.
39. As a friend, I want a Playlist whose name I've given another Playlist refused with what to do about it in the web UI, so that I'm not pointed at a flag I can't type.
40. As a friend, I want a file too large for the proxy in front of Seek to fail with a sentence telling me to import at `localhost` or with `seek import`, so that I know the file is fine and the route isn't.
41. As a friend, I want a file larger than Seek accepts refused with a sentence pointing at `seek import`, so that I have a way forward.
42. As a friend, I want a second import refused while one is running, so that two tabs can't trip over each other.
43. As a friend, I want an import that lost its hold on Syncs partway to say how far it got and that importing again carries on, so that I know nothing is broken.

### Live state
44. As a learner, I want every open page to show an imported entry and its counts without a reload, so that a second tab or device isn't stale.
45. As a learner, I want an open Videos table to show the Videos an import completed, so that an existing Channel's page follows too.
46. As a friend, I want a Sync queued during an import to start as soon as the import ends, so that I'm not waiting on a poll.

### Safety and housekeeping
47. As a learner, I want another website to be unable to make my Seek import a file, so that browsing elsewhere can't add content to my Library.
48. As a learner, I want an uploaded Bundle treated as untrusted input exactly as `seek import` treats one, so that the web route is no softer than the command.
49. As a learner, I want an upload written straight to disk and never held in memory, so that a large Bundle can't exhaust the machine.
50. As a learner, I want uploads and built Bundles deleted on every path, and anything a crash left behind cleared at the next start, so that the data directory never fills with leftovers.
51. As a learner, I want a built Bundle reachable only through its own unguessable link, once, so that it isn't a standing copy of my Transcripts on a URL.
52. As a learner, I want both features behind Cloudflare Access like everything else when Seek is published, so that they open no new way in.

## Implementation Decisions

### What does not change
- The Bundle format, its validation, the merge rules, the Sync lease, and the two CLI commands are as Spec 0005 left
  them. The server calls the same export and import functions; it has no second implementation of either.
- The knowledge base's schema does not change, and there is no migration.
- No new dependency. In particular no multipart parser: the upload is a raw request body.

### Two small changes to the Bundle functions
- **How a refusal names the file.** Import's refusals name the Bundle by its path, which for an upload would be a
  temporary path on the server. The import function takes an optional name to use for the Bundle in its refusals,
  defaulting to the path. The server passes "The file", giving "The file is not a Seek Bundle", "The file is damaged
  or has been altered: …", and "The file was embedded with …". The CLI passes nothing, and its sentences are
  unchanged.
- **The Playlist-name refusal is told apart.** It is raised as a kind of its own, still one of the user-facing
  refusals and carrying the name that is taken, so the server can say what to do in the web UI. The CLI still prints
  the `--name` sentence.

### Routes
- `POST /api/channels/{id}/bundles` and `POST /api/playlists/{id}/bundles` build a Bundle of that entry and answer
  with `{id, name, videos, segments, size_bytes, playlist_filter_left_out}`: the export report, plus the id the
  built Bundle is collected under.
- `GET /api/bundles/{id}` sends a built Bundle as a download.
- `POST /api/bundles` imports the Bundle that is the request body and answers with the import report.
- Refusals answer with `{"detail": <sentence>}` like every other route, and the dialogs show the sentence as it
  stands. The user-facing refusal the Bundle functions raise joins the app's table of errors that map to a status:
  422 for it, 409 for the Playlist-name refusal and for the server's own "not now" refusals below, 404 for an entry
  or a built Bundle that isn't there, 413 for a file over the cap, 415 for a body that isn't
  `application/octet-stream`. The dialogs read only the sentence, never the status.

### Export
- The handler finds the entry by the id in the URL (a Channel outside the Library is not found) and passes the
  export function the entry's YouTube id, not its name: Channel names are not unique, and a name two Channels share
  would be refused as ambiguous.
- The function runs in a worker thread, since it opens its own connection, and writes to a file in a fresh
  directory of the temporary area (below). It needs no lease and no model, so it runs during a Sync and on a Paused
  entry, as the command does.
- The answer carries an id that is long, random, and good for one download. `GET /api/bundles/{id}` sends the file
  as `application/octet-stream` with its length and `Content-Disposition: attachment`, and deletes it when the
  response ends, whether or not it was sent whole. A second request for the same id is 404. A download that broke
  is exported again.
- Building and downloading are two requests so that a refusal reaches the dialog as a sentence, "Building…" has an
  end the page can see, and the browser saves the file itself instead of holding 255 MB in the page's memory.
- A built Bundle nobody collects is deleted ten minutes after it was built.
- **The file name** is the entry's name with path separators, the characters Windows forbids in a name
  (`< > : " / \ | ? *`), and control characters each replaced by `_`, leading and trailing dots and spaces removed,
  cut to 100 characters, and `bundle` when nothing is left; then `.seek`. The header carries it twice, as an ASCII
  fallback and in the UTF-8 form, so a name in another script or with an emoji survives.
- The server counts the Videos again when it builds, so an entry that lost its last indexed Video since the page
  loaded is refused with the command's sentence.

### Import
- The body is the file's bytes with `Content-Type: application/octet-stream`. Any other content type is refused.
  No file name is sent: the dialog already shows it, and the server has no use for one.
- In order, before anything is stored:
  1. One import at a time in a server. A second, while one is uploading or importing, is refused: "Another import
     is running; try again when it has finished."
  2. A Sync that is running or queued refuses the import: "A Sync is running or waiting to run; import when it has
     finished." This is the same condition the dialog disables on.
  3. A declared length over the cap is refused.
- An upload refused at one of those steps is still read to its end, up to the cap, and discarded, so the browser
  receives the sentence and not a dropped connection.
- The body is then streamed to a file in a fresh directory of the temporary area, a chunk at a time, counting
  bytes. Nothing of it is held in memory. A body that passes the cap is refused and what was written is deleted.
- **The cap is 2 GB**, a constant: "The file is larger than 2 GB, the most the web UI imports; import it with
  `seek import`." The largest Bundle of the reference Library is 255 MB, and the whole Library would be about
  650 MB. The cap exists because the upload is written to the data directory's disk by anyone past Access. The app
  factory takes it as a parameter, as it takes its other test-tunable values.
- The import function then runs in a worker thread with no name and no progress callback. It takes the Sync lease
  as it does for the command, so a Sync that started after step 2 is still refused, with the command's sentence.
- An upload the browser abandons is discarded. Once the whole file has arrived, the import runs to its end whether
  or not the browser is still there.
- The answer is the import report as JSON: `{kind, id, name, youtube_id, created, filters, added, already_indexed,
  left_out}`. `id` is the entry's id in this Library, for the dialog to select it and start its Sync; `filters` is
  the Channel filters that arrived with a new Channel, else null; `left_out` maps each reason to its count.
- The Playlist-name refusal reads, here: "A Playlist named 'X' already exists; rename it, then import the file
  again, or import it under another name with `seek import --name`."
- When the import ends, however it ends, the server wakes its Sync worker, so a Sync queued meanwhile starts at
  once.

### Telling open pages
- When the import ends, including one that stopped partway with some Videos committed, the server publishes the
  existing "these Videos changed" event for each Channel the entry's Videos are credited to, naming the Playlists
  that include them. Every open page already reloads its Channels, its Playlists, and any open Videos table on that
  event, so no new event type is needed.
- It is published from the event loop after the worker thread returns, never from the thread.
- `seek import` beside a running server still tells it nothing, as before.

### Temporary files
- Uploads and Bundles being built live in one directory inside the data directory, created readable by the user
  alone. Not the system's temporary directory: that can be memory-backed, which a 255 MB file should not be, and the
  data directory is on the disk the user already sized for the knowledge base.
- Each upload and each build gets a fresh, unguessably named directory there, removed whole when it is finished
  with: after an import ends or is refused, after a download's response ends, when a build fails, and when a built
  Bundle goes uncollected.
- The server empties the directory at start, before it serves, which clears whatever a crash or a stop left. The
  CLI never uses it.

### Web UI: Export
- An Export button on the Channel page and on the Playlist page, with the actions that concern the entry as a whole
  (Rename, Pause, Remove).
- It is disabled when the entry's count of indexed Videos is zero, with a tooltip: "No indexed Videos to export
  yet." The tooltip has to show on a disabled control, which doesn't raise pointer events of its own.
- Pressing it opens a dialog titled "Export <name>" with: the count of indexed Videos; "The file contains the
  creators' full Transcripts, so choose who you share it with."; and, for a Channel with a Playlist filter, "The
  Channel's Playlist filter is left out, so the recipient's Syncs will bring in its other Videos." It has Cancel and
  one Export button, which is not styled as destructive.
- Export becomes "Building…" and is disabled until the build answers. The page then sends the browser to the
  download link, as a relative URL so it follows a proxy prefix, and the dialog closes. A refusal shows in the
  dialog as an alert and leaves it open.

### Web UI: Import
- Both Add dialogs gain a second path under the URL form, "or import a `.seek` file": a file picker limited to
  `.seek`. It is one implementation, mounted in both. There is no Import button anywhere else.
- Choosing a file shows its name and size and an Import button. There is no name field.
- While any Sync is running or queued, the path is disabled and says so beside it, in the server's words. Syncs are
  already held live at the top of the app.
- While it works, the dialog shows "Importing…", its controls are disabled, and it can't be dismissed.
- On success the page reloads its Channels and Playlists, selects the entry on the tab of its kind, and the dialog
  shows the report: "Imported the Channel <name>" or "Imported the Playlist <name>"; the three counts; each
  left-out reason with its count, as the server gave it; "It was already in the Library, and keeps its name and
  settings." or, for a new Channel with filters, "It arrived with its filters: …" in the words the Filters dialog
  uses; and "The Bundle's text came from whoever made the file, and is only as trustworthy as they are." Then
  "Start a Sync" and "Close".
- "Start a Sync" starts the entry's Sync through the existing route and closes the dialog. It replaces the command's
  `seek sync --channel ID` line.
- A refusal shows as an alert and keeps the chosen file, so an import refused for a Sync can be tried again.
- **A failure that carries no sentence of Seek's** (the response isn't Seek's JSON, or the request fails outright)
  shows: "The file didn't reach Seek. A proxy in front of it may refuse a file this large; import it at `localhost`
  on the machine Seek runs on, or with `seek import`." The page doesn't guess the proxy's limit in advance.
- The upload has its own request function, since the shared one sends JSON only. It uses a relative URL.

### Security
- **Cross-site requests.** A page on another site can't send `application/octet-stream` without a preflight, which
  Seek never grants, and the proxy middleware already refuses a foreign Origin. Requiring that content type is what
  closes the upload to a cross-site form; it is checked before the body is read.
- A build takes no body, so it relies on the Origin check as the other body-less routes do (starting a Sync, for
  one). What a forged build could do is write a file nobody can collect, which expires.
- A built Bundle is collected by an id from the operating system's random source, and only once.
- The upload is untrusted input from its first byte: stored in a directory only the user can read, opened by the
  import function exactly as ADR 0007 describes, and deleted afterwards. Nothing about it is trusted because it
  came through the web UI.
- Through the published host both features sit behind Cloudflare Access with every other route. No route is
  loopback-only: the grilling session decided both work wherever the UI does.
- The file name in the download header is built from the sanitised name only, so a name can't add a header or a
  path.

### Docs
- README: "Sharing a Channel or Playlist" leads with the web UI (Export on the entry's page, import in the Add
  dialogs) and keeps the commands, and says a large Bundle may be refused by a proxy and imports at `localhost` or
  with `seek import`. "Publishing through a reverse proxy" gets a line on the same.
- HANDOFF: an update entry, and the routes and the temporary directory in the conventions.
- ADR 0007 gains a dated note, not a successor: import also runs inside the server now, on an uploaded file, in a
  worker thread, under the same lease, so "the first command to write beside a running server" becomes a second
  writer that is either the CLI's process or a thread of the server's. The untrusted file now also arrives over
  HTTP, and the note records the content-type requirement, the cap, and that it is never held in memory.
- CONTEXT.md needs no change.

## Testing Decisions

- Tests exercise external behaviour: what the routes answer, and what the app then shows through its own surfaces
  (the Channel and Playlist lists, search and its Citations, the event stream, Syncs). They do not assert table
  contents or the inside of a Bundle. The temporary directory being empty is asserted on the file system, since
  "nothing is left behind" is the behaviour.
- **Two seams, both existing; no new one.** Agreed with Drew on 2026-10-11.
- **Seam 1, the HTTP API**, in a new test module on the existing harness (`running`, `event_stream`, `Gate`,
  `add_channel`, `add_playlist`, `sync`, `search`). Apps are built on a `Config` naming the fake embedder's model,
  as Spec 0005's tests build theirs, because the Bundle functions open the knowledge base with the `Config`'s. A
  round trip uses two apps on two data directories: the sender's builds and serves the Bundle, and its bytes are
  posted to the friend's. Covered:
  - A Channel round trip and a Playlist round trip: built, downloaded, imported, then listed and searchable on the
    friend's app, with the report's kind, name, id, and counts. The report's `id` starts a Sync through the
    existing route.
  - The download's headers: attachment, the `.seek` name, and names that need sanitising (a slash, a quote, an
    emoji, a name of nothing but dots).
  - A built Bundle is served once; the second request is 404. One left uncollected is gone after the expiry, with
    the expiry shortened through the app factory.
  - Export of a Paused entry, of an entry during a Sync held by a `Gate`, of a Channel that shares its name with
    another; and the refusal for an entry with no indexed Videos and for an id that isn't there.
  - A Channel with a Playlist filter reports that it was left out.
  - Import refusals, each asserting the sentence and that the Library is unchanged: bytes that aren't a Bundle
    (called "The file", with no path in the sentence), a Bundle of another embedding model, a Playlist name already
    taken, a Sync running, a Sync queued, another import running (the first held open by a request body that
    pauses before its last chunk), a body over a small cap both declared and undeclared, and a content type other
    than `application/octet-stream`.
  - An import into an existing entry reports `created: false` and leaves its name alone.
  - After an import, a subscriber to the event stream receives the Videos-changed event for the entry's Channel,
    and a Sync queued while the import ran starts without waiting for the poll.
  - The temporary directory is empty after each path above, and a leftover planted before the app starts is gone
    once it has started.
  - Through a published host with Access configured, in the remote-access tests' pattern: the three routes need a
    token like any other, and work under a forwarded prefix with one.
- **Seam 2, the browser**, in the smoke module with `serving` and `browsing`, for what only a browser shows:
  - Export from a Channel page: the dialog's count and Transcripts line, "Building…", and a download whose
    suggested name is `<name>.seek`.
  - That downloaded file imported in a second served app's Add Channel dialog: "Importing…", the report, the entry
    selected, and "Start a Sync" starting one.
  - A Playlist Bundle imported through the Add Channel dialog selects the Playlist and says so.
  - Export is disabled with its tooltip on an entry with no indexed Videos, and the import path is disabled with
    its reason while a Sync is held by a `Gate`.
  - With the upload route answered by the test as a proxy would (a 413 with an HTML body), the dialog shows the
    "didn't reach Seek" sentence.
- A browser leaving mid-upload or mid-import depends on the HTTP server's handling of a dropped connection, which
  the in-process harness doesn't reproduce. Those two tests use `serving` and a client that drops its connection.
- Not tested again: the merge rules and validation, which Spec 0005's tests own. Those tests pass unchanged; the
  two changes to the Bundle functions are observed at seam 1, and the CLI's sentences by the tests that already
  assert them.
- Verification: `uv run pytest -q && uv run mypy`, and the web typecheck and build. A fresh worktree needs
  `pnpm --dir web install --frozen-lockfile` first.
- Prior art: the Bundle, channels, playlists, sync-events, remote-access, and smoke test modules.

## Out of Scope

- Chunked or resumable uploads, and any way to get a file past a proxy's size limit. The answer for a large Bundle
  is `localhost` or `seek import`.
- A name field at import, and progress by Video while importing or building.
- An Import button outside the Add dialogs, and Export in the Library's rows.
- Cancelling an import that has begun.
- Exporting a Group, several entries, or the whole Library; anything else Spec 0005 put out of scope.
- A setting for the upload cap or the expiry of a built Bundle.
- Telling a running server about a `seek import` run beside it.
- A visible file icon for `.seek` files, or opening one by double-click, which is the desktop shell's job.
- Drag and drop of a `.seek` file onto the page.

## Further Notes

- **Settled in this spec, beyond the grilling session's decisions**, for the critique to weigh:
  - building and downloading as two requests, with a one-time id and a ten-minute expiry;
  - the temporary directory inside the data directory, emptied at start;
  - a 2 GB cap on an upload, fixed;
  - one import at a time in a server, and the server refusing on a queued Sync as well as a running one;
  - refusals saying "The file", and the web wording of the Playlist-name refusal, each a small change to the import
    function;
  - an Import button after the file is chosen, where the session said only that there is no name field;
  - the dialog not dismissable while importing;
  - the statuses, which the page never reads.
- Measured on the reference Library on 2026-10-11: its largest Channel (898 Videos, 23,919 Segments) is a 255 MB
  Bundle, 15 s to export and 23 s to import.
- Not verified: that Cloudflare caps an upload at 100 MB on this plan. The spec doesn't depend on the number. If it
  holds, that Channel's Bundle can't be imported through the published host, and the fallback sentence is what its
  recipient sees.
- A proxy also limits how long it waits for an answer. A build or an import that outlasts it shows the fallback
  sentence in the dialog although the server finishes: the import's entry then appears through the event stream,
  and the built Bundle expires uncollected. At the measured rates that needs a Bundle several times the largest
  real one, so it is accepted.
- An export's count in the dialog comes from the page and the Bundle's from the server a moment later, so they can
  differ by what a running Sync finished in between.
- A browser that retries a download from its own downloads list gets a 404, since a built Bundle is served once.
  Exporting again is the remedy.
