# 01: Export a Channel from its page

**What to build:** On a Channel's page I press Export, confirm in a dialog that tells me what I'm about to share, and my browser downloads the Channel's Bundle as `<name>.seek`, on whichever device I'm using. Nothing of it stays on the server. This is the tracer bullet: it brings in the build and download routes and the temporary directory that the later tickets reuse. See Spec 0006 §Routes, §Export, §Temporary files, §Web UI: Export, §Security.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] The Channel page has an Export button with the actions that concern the entry as a whole (Rename, Pause, Remove), and none in the Library's rows.
- [x] Export is disabled when the Channel has no indexed Videos, with the tooltip "No indexed Videos to export yet." The tooltip shows although the control is disabled.
- [x] Pressing Export opens a dialog titled "Export <name>" with the count of indexed Videos, the line that the file contains the creators' full Transcripts, and, for a Channel with a Playlist filter, the line that the filter is left out. It has Cancel and one Export button, not styled as destructive.
- [x] Export becomes "Building…" and is disabled until the build answers. The download then starts through a link carrying the `download` attribute, as a relative URL, and the dialog closes. An error from the link is a failed download, never a navigation away from the app.
- [x] A refusal shows in the dialog as an alert and leaves it open. The build keeps its own busy and error state, apart from the page's shared runner of changes.
- [x] Building a Channel's Bundle is one request that answers with the report (name, Videos, Segments, size, whether a Playlist filter was left out) and the id the built Bundle is collected under. It calls the existing export function in a worker thread; there is no second implementation.
- [x] The Channel is found by the id in the URL; one outside the Library, or an id that isn't there, is not found. The export function is given the Channel's YouTube id, so a Channel that shares its name with another exports.
- [x] A Paused Channel exports, and so does one whose Sync is running.
- [x] The user-facing refusal the Bundle functions raise maps to a status with its sentence as `detail`. An entry with no indexed Videos is refused with the command's sentence, counted again by the server when it builds.
- [x] Collecting a built Bundle sends it as `application/octet-stream` with its length and as an attachment. It is served once: the file is deleted when the response ends, whether or not it was sent whole, and a second request is not found.
- [x] The id is long and from the operating system's random source.
- [x] The file name is the Channel's name sanitised as the spec lays out (separators, the characters Windows forbids, and control characters replaced; dots and spaces trimmed; cut to 100 characters; `bundle` when nothing is left) plus `.seek`. The header is built by hand and carries it in the UTF-8 form and as an ASCII fallback.
- [x] Bundles being built live in one directory inside the data directory, readable by the user alone, each in a fresh, unguessably named directory that is removed whole after the download's response ends and when a build fails.
- [x] HTTP tests cover: a build and its download (the report's counts, the headers), names that need sanitising (a slash, a quote, an emoji, nothing but dots), served once, a Paused Channel, a Channel mid-Sync held by a `Gate`, a Channel sharing its name, a Playlist filter reported as left out, no indexed Videos, an id that isn't there, and the temporary directory empty after each.
- [x] A browser test covers the dialog's count and Transcripts line, "Building…", a download whose suggested name is `<name>.seek`, and Export disabled with its tooltip on a Channel with nothing indexed.

## Comments

### 2026-10-12: landed on `bundles-web-ui/ticket-01`

**What landed.** `POST /api/channels/{id}/bundles` builds a Channel's Bundle with `bundles.export_channel` in a worker thread and answers 201 with the report and a one-time id; `GET /api/bundles/{id}` sends it once as a download and removes it when the response ends. Both are in the new `src/seek/bundles_api.py`. The Channel page has an Export button and the dialog (`web/src/library/ExportDialog.tsx`). HTTP tests are in `tests/test_bundles_api.py`; the browser test is `test_exporting_a_channel_from_its_page_downloads_its_bundle_under_the_channels_name` in the smoke module.

**Readings taken where the spec left room.**
- The build answers **201**. The spec names no status for it; the page never reads one.
- The temporary directory is `<data_dir>/tmp`, as `Config.temporary_dir`. It is created (mode 0700) in the app's lifespan, after the knowledge base opens and before anything is served, so a test that lists it fails loudly on a server that never made it.
- The file name is made from the name in the export's report, which is the Channel's name as the export read it.
- The dialog can't be dismissed while it builds (Cancel disabled, the close button hidden): closing it would leave a download that starts with nothing on screen, or a built Bundle nobody collects before ticket 05 gives those an expiry.
- The dialog's count line reads "2 indexed Videos go into one `.seek` file." The page's copy uses typographic apostrophes, so the two spec sentences do too.
- `channels._get_channel` became the public `channels.get_channel`, its first caller outside the module.
- A server that can't create a directory in the temporary directory refuses the build with "Could not write the Bundle: <the system's reason>" (422) where it would have answered 500.

**The security review of `46dfdc6`** reported two things.
1. *Fixed here.* Mapping `SyncCommandError` to a status sends its sentence to the page, and three of export's refusals name the destination, which through the build route is a path in the server's data directory. `export_channel` and `export_playlist` now take `called: str | None = None`, what to call the Bundle in a refusal in place of its path; the route passes `bundles_api.CALLED` ("the Bundle"). With a name given, a failed write also drops the file name the system's error carries, keeping its reason alone. `seek export` passes nothing and prints what it printed. The name is used as it stands, so of the three only "Could not write the Bundle: …" reads as a sentence with "the Bundle"; the other two ("… is a directory", "… already exists") can't arise in a fresh directory.
   - *Tested off the two seams, knowingly.* Through the route, the write that fails inside the fresh directory can't be forced portably: the directory is made and written within one request. So the name in export's own refusals is tested on the function, in `tests/test_bundles.py` beside Spec 0005's refusal tests (`test_export_told_what_to_call_the_bundle_keeps_its_path_out_of_every_refusal`), and at the HTTP seam a build with a read-only temporary directory asserts the sentence holds no path.
2. *Left to ticket 05, by design.* A built Bundle nobody collects stays on disk and in the router's map. Noted in ticket 05's comments.

**Not handled, and small.**
- A Channel whose name is exactly another Channel's YouTube channel id is refused as ambiguous, since the export function matches a name or an id.
- The download honours a `Range` header (the framework's file response does) and still deletes the Bundle afterwards.
- `bundles.py`'s opening docstring still says both commands run "never through the server"; ticket 06 owns the wording.

**For tickets 02–06: reuse these, don't copy them.**
- `bundles_api.bundles_router(config, database, area)`. Inside it, `build(export)` takes a function from a path to an `ExportReport`, runs it in a thread into a fresh directory, removes the directory if it fails, and registers the Bundle. A Playlist's route is `build(lambda path: export_playlist(config, playlist.youtube_playlist_id, path, called=CALLED))` after a lookup by id (`playlists` has no public one yet).
- `bundles_api.TemporaryArea`: `prepare()` (called in the lifespan; ticket 05's clearing at start belongs there), `new_directory()`, `remove(directory)`. An upload gets its directory from the same `new_directory()`.
- The router's `built` map (id to `_Built(path, file_name)`) and `_ServedOnce`, the response that removes the directory in a `finally`. Ticket 05's expiry pops from that map and calls `TemporaryArea.remove`.
- `bundles_api.bundle_file_name(name)` and `BuiltBundle`, the build's answer.
- `app.ERROR_STATUS` has `SyncCommandError: 422`. Ticket 03 adds the Playlist-name refusal's own type beside it, and gives `import_bundle` the same `called` idiom (its `name` parameter is already the entry's name), passing "The file".
- Web: `ExportButton({indexedVideos, onClick})` and `ExportDialog({name, indexedVideos, playlistFilterLeftOut?, build, open, onOpenChange})` in `library/ExportDialog.tsx`; `api.buildChannelBundle`, `bundleUrl(id)`, and the `BuiltBundle` type in `lib/api.ts`. A Playlist page passes `build={() => api.buildPlaylistBundle(id)}` and leaves `playlistFilterLeftOut` out.
- Tests: `harness.bundle_config` (a second copy of the one in `tests/test_bundles.py`, which was left untouched); in `tests/test_bundles_api.py`, the `sender` and `friend` fixtures, `app_on`, `held(config)` (what the temporary directory holds) and `mode(path)`. The first test there imports the downloaded bytes with `import_bundle` directly; ticket 03 can post them to the friend's app instead. The browser test saves its download to `tmp_path / "saved.seek"`, the file ticket 03's browser test imports.
