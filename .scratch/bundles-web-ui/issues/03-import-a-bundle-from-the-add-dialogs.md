# 03: Import a Bundle from the Add dialogs

**What to build:** In the Add Channel dialog or the Add Playlist dialog I choose "or import a `.seek` file", pick the file, and press Import. Seek imports it, either kind in either dialog, shows me what was added, selects the new entry in my Library, and offers to start a Sync. Its Videos are searchable at once, and every other open page shows the entry without a reload. A file Seek can't use is refused in a sentence about "the file". See Spec 0006 §Two small changes to the Bundle functions, §Routes, §Import, §Telling open pages, §Temporary files, §Web UI: Import, §Security.

This ticket leaves two things to the next ones: refusing while a Sync or another import is in the way (04), and the size cap, the proxy sentence, and abandoned uploads (05).

**Blocked by:** 01 (Export a Channel from its page), for the temporary directory and for a real Bundle to import in tests.

**Status:** ready-for-agent

- [ ] Both Add dialogs have a second path under the URL form, "or import a `.seek` file": a file picker limited to `.seek`. It is one implementation, mounted in both. There is no Import button anywhere else.
- [ ] Choosing a file shows its name and size and an Import button. There is no name field: the entry takes the Bundle's name.
- [ ] While it works the dialog shows "Importing…", its controls are disabled, and it can't be dismissed. There is no count by Video.
- [ ] The file is sent as the raw request body with the content type `application/octet-stream`, through a request function of its own, to a relative URL. No file name is sent.
- [ ] The server refuses any other media type before reading the body, ignoring a parameter after it.
- [ ] The body is streamed to a file in a fresh directory of the temporary directory, a chunk at a time, never held in memory, with the writes kept off the event loop. That directory is removed whole however the import ends.
- [ ] The existing import function then runs in a worker thread, with no name and no progress callback. Validation, merge rules, and the Sync lease are untouched.
- [ ] The import function takes an optional name to use for the Bundle in its refusals, defaulting to the path. The server passes "The file", so no refusal shown in the dialog holds a path on the server. `seek import` prints what it printed before.
- [ ] The Playlist-name refusal is raised as a kind of its own, carrying the name that is taken. The server answers it with "A Playlist named 'X' already exists; rename it, then import the file again." `seek import` still prints the `--name` sentence. Both kinds of refusal are entered in the app's table of errors, which is looked up by exact type.
- [ ] The answer is the report as JSON: kind, the entry's id in this Library, name, YouTube id, whether it was created, the filters that arrived with a new Channel, added, already indexed, and each left-out reason with its count. The handler finds the Library id by the entry's kind and YouTube id once the thread returns.
- [ ] On success the page reloads its Channels and Playlists, selects the entry on the tab of its kind, and the dialog shows the report: "Imported the Channel <name>" or "Imported the Playlist <name>"; the three counts; each left-out reason as the server gave it; the already-in-the-Library line or the arrived-filters line in the Filters dialog's words; and the line that the Bundle's text is only as trustworthy as whoever made it.
- [ ] The report has "Start a Sync", which starts the entry's Sync through the existing route and closes the dialog, and "Close".
- [ ] A refusal shows as an alert, keeps the chosen file, and reloads the page's Channels and Playlists.
- [ ] When an import completes, the server publishes the existing Videos-changed event for the entry as a Sync of it would, using the existing listing by creator with the entry as its source, from the event loop after the thread returns. An import that ends in a refusal publishes nothing.
- [ ] HTTP tests cover, with two apps on two data directories: a Channel round trip and a Playlist round trip (built, downloaded, imported, then listed and searchable on the friend's app, with the report's kind, name, id, and counts); the report's id starting a Sync; an import into an existing entry reporting that it was not created and leaving its name alone; and a subscriber to the event stream receiving the event.
- [ ] HTTP tests cover the refusals, each asserting the sentence and that the Library is unchanged: bytes that aren't a Bundle (called "The file", with no path), a Bundle of another embedding model, a Playlist name already taken, and a content type other than `application/octet-stream`. The temporary directory is empty after each path.
- [ ] Browser tests cover: the file ticket 01's test downloads imported in a second served app's Add Channel dialog ("Importing…", the report, the entry selected, "Start a Sync" starting one); and a Playlist Bundle imported through the Add Channel dialog selecting the Playlist and saying so.
- [ ] Spec 0005's tests pass unchanged.
