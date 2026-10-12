# 03: Import a Bundle from the Add dialogs

**What to build:** In the Add Channel dialog or the Add Playlist dialog I choose "or import a `.seek` file", pick the file, and press Import. Seek imports it, either kind in either dialog, shows me what was added, selects the new entry in my Library, and offers to start a Sync. Its Videos are searchable at once, and every other open page shows the entry without a reload. A file Seek can't use is refused in a sentence about "the file". See Spec 0006 §Two small changes to the Bundle functions, §Routes, §Import, §Telling open pages, §Temporary files, §Web UI: Import, §Security.

This ticket leaves two things to the next ones: refusing while a Sync or another import is in the way (04), and the size cap, the proxy sentence, and abandoned uploads (05).

**Blocked by:** 01 (Export a Channel from its page), for the temporary directory and for a real Bundle to import in tests.

**Status:** done

- [x] Both Add dialogs have a second path under the URL form, "or import a `.seek` file": a file picker limited to `.seek`. It is one implementation, mounted in both. There is no Import button anywhere else.
- [x] Choosing a file shows its name and size and an Import button. There is no name field: the entry takes the Bundle's name.
- [x] While it works the dialog shows "Importing…", its controls are disabled, and it can't be dismissed. There is no count by Video.
- [x] The file is sent as the raw request body with the content type `application/octet-stream`, through a request function of its own, to a relative URL. No file name is sent.
- [x] The server refuses any other media type before reading the body, ignoring a parameter after it.
- [x] The body is streamed to a file in a fresh directory of the temporary directory, a chunk at a time, never held in memory, with the writes kept off the event loop. That directory is removed whole however the import ends.
- [x] The existing import function then runs in a worker thread, with no name and no progress callback. Validation, merge rules, and the Sync lease are untouched.
- [x] The import function takes an optional name to use for the Bundle in its refusals, defaulting to the path. The server passes "The file", so no refusal shown in the dialog holds a path on the server. `seek import` prints what it printed before.
- [x] The Playlist-name refusal is raised as a kind of its own, carrying the name that is taken. The server answers it with "A Playlist named 'X' already exists; rename it, then import the file again." `seek import` still prints the `--name` sentence. Both kinds of refusal are entered in the app's table of errors, which is looked up by exact type.
- [x] The answer is the report as JSON: kind, the entry's id in this Library, name, YouTube id, whether it was created, the filters that arrived with a new Channel, added, already indexed, and each left-out reason with its count. The handler finds the Library id by the entry's kind and YouTube id once the thread returns.
- [x] On success the page reloads its Channels and Playlists, selects the entry on the tab of its kind, and the dialog shows the report: "Imported the Channel <name>" or "Imported the Playlist <name>"; the three counts; each left-out reason as the server gave it; the already-in-the-Library line or the arrived-filters line in the Filters dialog's words; and the line that the Bundle's text is only as trustworthy as whoever made it.
- [x] The report has "Start a Sync", which starts the entry's Sync through the existing route and closes the dialog, and "Close".
- [x] A refusal shows as an alert, keeps the chosen file, and reloads the page's Channels and Playlists.
- [x] When an import completes, the server publishes the existing Videos-changed event for the entry as a Sync of it would, using the existing listing by creator with the entry as its source, from the event loop after the thread returns. An import that ends in a refusal publishes nothing.
- [x] HTTP tests cover, with two apps on two data directories: a Channel round trip and a Playlist round trip (built, downloaded, imported, then listed and searchable on the friend's app, with the report's kind, name, id, and counts); the report's id starting a Sync; an import into an existing entry reporting that it was not created and leaving its name alone; and a subscriber to the event stream receiving the event.
- [x] HTTP tests cover the refusals, each asserting the sentence and that the Library is unchanged: bytes that aren't a Bundle (called "The file", with no path), a Bundle of another embedding model, a Playlist name already taken, and a content type other than `application/octet-stream`. The temporary directory is empty after each path.
- [x] Browser tests cover: the file ticket 01's test downloads imported in a second served app's Add Channel dialog ("Importing…", the report, the entry selected, "Start a Sync" starting one); and a Playlist Bundle imported through the Add Channel dialog selecting the Playlist and saying so.
- [x] Spec 0005's tests pass unchanged.

## Comments

### 2026-10-12: landed on `bundles-web-ui/ticket-03`

**What landed.** `POST /api/bundles` in `src/seek/bundles_api.py` (`import_uploaded_bundle`): it checks the content type, streams the body to `upload.seek` in a fresh directory of the temporary directory, runs `bundles.import_bundle` in a worker thread with `called="The file"`, removes the directory however that ends, looks the entry's id up by kind and YouTube id, publishes the Videos-changed event for each creator `videos.listed_by_creator` gives, and answers with the report. `import_bundle` takes `called` as export does, and the Playlist-name refusal is `bundles.PlaylistNameTaken`, entered in `app.ERROR_STATUS` at 409. On the web, `web/src/library/ImportBundle.tsx` holds the one implementation (`useBundleImport`, `ImportBundle`, `ImportReport`), mounted in both Add dialogs; `api.importBundle` sends the file through `upload()` in `lib/api.ts`. Eleven new HTTP tests (seventeen cases) in `tests/test_bundles_api.py`, and two browser tests in the smoke module, one of them ticket 01's carried on.

**Readings taken where the spec or ticket left room.**
- A content type other than `application/octet-stream` answers 415 with "A Bundle is imported as the body of the request, sent as application/octet-stream". The spec gives the status and no sentence; the dialog can't produce one. The type is compared without regard to case, and whatever follows a `;` is dropped. It is the server's own refusal, so it is an `HTTPException`, not an entry in the table.
- "Before the body is read" is tested by driving the app with a `receive` that records being asked: it never is.
- An import answers **200**.
- The upload's file is created readable by the user alone (0600), as a built Bundle's is, inside its 0700 directory.
- `PlaylistNameTaken(name, remedy)` makes the sentence from the name and what to do about it; the remedy defaults to the command's `--name`. The route catches it and raises the same type with "rename it, then import the file again.", so the status still comes from the table by exact type.
- In the dialog the path sits inside the URL form, under its fields and above the footer that holds Look up, since the footer is the dialog's bottom edge. The URL form's own controls are disabled while a Bundle imports, and the close button is hidden.
- The report takes over the dialog's content, titled "Imported the Channel <name>" or "Imported the Playlist <name>". Its close button is hidden too, so "Close" is the one way out beside "Start a Sync". The counts read "2 Videos added, 0 already indexed, 0 left out." ("1 Video" for one), with each left-out reason and its count listed under them.
- A new Channel that had no filters is reported with `filters` holding four nulls, not null, as the import function reports it; the arrived-filters line shows only when there is something to say. Its words are `filtersSummary`'s, which the Channel page already uses.
- A file's size reads "37 KB" or "255.0 MB" (`formatSize` in `lib/format.ts`), as `seek export` prints one.
- A "Start a Sync" that the server refuses shows its sentence in the report, which stays open.
- A dialog that is closed forgets the chosen file and any refusal.

**Tests changed, and why.**
- The two round-trip tests in `tests/test_bundles_api.py` now post the downloaded bytes to the friend's app where they called `import_bundle`, and assert the report as well; nothing they asserted before was dropped. The module no longer imports the function.
- Ticket 01's browser test is now `test_exporting_a_channel_from_its_page_downloads_its_bundle_which_a_friends_seek_imports_in_its_add_dialog`: it goes on to import `saved.seek` in a second served app. Its Channel's filters gained `published_after`, so the report has a filter to show.
- `app_on` takes an optional embedder, for a sender whose Seek uses another model.

**The commit security review** reported one thing new, on `f223c5a`: `_store` writes an upload to the data directory's disk with no limit on its size. *Left to ticket 05, by design:* that is its 2 GB cap, and where the cap hooks into the handler is noted in ticket 05's comments. Nothing was built for it here. (The review's other two entries are ticket 01's, carried over: one fixed there, one already with ticket 05.) It found nothing in `89ec293`.

**Not handled, and small.**
- An entry removed between the import's end and the lookup of its id answers 500.
- A server that can't create the upload's directory, or whose disk fills while it stores the upload, answers 500 without a sentence of Seek's.
- The 415 is sent without the body being read, so a client other than the page that sends a large body under another type may see the connection reset before the sentence.
- A Look up still in flight doesn't disable Import.
- This ticket's opening paragraph cites "§Two small changes to the Bundle functions"; since ticket 01 the spec's heading says three.

**For tickets 04–06.**
- **04, the server.** The ordered checks go in `import_uploaded_bundle` between the content-type check and `area.new_directory()`; nothing is stored before that line. The handler's `finally` (which removes the directory) is where the hold is given up and the worker woken, so `bundles_router` needs the worker's `wake` as `syncs_router` gets it. An upload refused there still has to be read to its end: `async for _ in request.stream()`.
- **04, the page.** `useBundleImport` holds the import's state and `ImportBundle` renders the path; the disabled state and its reason belong on those two. Syncs have to come down from `App.tsx` through `useLibraryDialogs` to both dialogs.
- **05, the server.** A declared length is read from the header before the checks above; the count of bytes goes in `_store`, whose caller already removes what was written. An abandoned upload raises `ClientDisconnect` out of `request.stream()`, and the `finally` already removes its directory. For an import to outlive its request, the thread is not enough: the request's task being cancelled would run the `finally` under it and skip the lookup and the event, so the import, the lookup, and the publishing need a task of their own.
- **05, the page.** `upload()` in `lib/api.ts` is where a failure with no sentence of Seek's is told apart: today a response that isn't Seek's JSON throws "Request failed (status)" and a request that fails outright throws the browser's own error. The cap check belongs in `useBundleImport`'s `choose`.
- **Tests.** In `tests/test_bundles_api.py`: `import_file(client, content, content_type)`, `bundle_of(client, "channels/<id>")`, and `library(client)` (the Channels, the Playlists, and what a search finds, for "the Library is unchanged"). The test of an upload arriving in pieces sends an async generator as the body, which the in-process transport pulls from lazily: the pattern for a body that pauses before its last chunk. In the browser, the Import button is found with `exact=True`, since the file picker is itself a button named "or import a .seek file".
- **06.** `bundles_api.py`'s opening docstring now covers import. `bundles.py`'s still says both commands run "never through the server".
