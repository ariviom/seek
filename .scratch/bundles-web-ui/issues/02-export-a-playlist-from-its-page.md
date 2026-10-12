# 02: Export a Playlist from its page

**What to build:** A Playlist's page gets the same Export button and dialog as a Channel's, and my browser downloads the Playlist's Bundle as `<name>.seek`. Everything ticket 01 built for a Channel (the one-time download, the file name, the temporary directory, the dialog) is reused, not copied. See Spec 0006 §Routes, §Export, §Web UI: Export.

**Blocked by:** 01 (Export a Channel from its page).

**Status:** done

- [x] The Playlist page has an Export button with the actions that concern the entry as a whole, disabled with the same tooltip when the Playlist has no indexed Videos.
- [x] The dialog is the one the Channel page uses: titled "Export <name>", with the count of indexed Videos and the Transcripts line. It never shows the Playlist-filter line, which is a Channel's.
- [x] Building a Playlist's Bundle is a request of the same shape as a Channel's, answering with the report and the id to collect it under. The Playlist is found by the id in the URL and the export function is given its YouTube playlist id.
- [x] A Paused Playlist exports, and so does one whose Sync is running.
- [x] A Playlist with no indexed Videos, and an id that isn't there, are refused as a Channel's are.
- [x] The built Bundle is collected, named, served once, and deleted exactly as a Channel's is, through the same route.
- [x] HTTP tests cover a Playlist's build and download, a Paused Playlist, no indexed Videos, and an id that isn't there, with the temporary directory empty after each.
- [x] A browser test, or an addition to ticket 01's, covers Export from a Playlist page down to the download's suggested name.

## Comments

### 2026-10-12: landed on `bundles-web-ui/ticket-02`

**What landed.** `POST /api/playlists/{id}/bundles` in `src/seek/bundles_api.py` finds the Playlist by id and hands ticket 01's `build` a call of `bundles.export_playlist` with the Playlist's YouTube playlist id and `called=CALLED`. The download route, the file name, and the temporary directory are ticket 01's, untouched. The Playlist page mounts `ExportButton` and `ExportDialog` beside Pause, with `build={() => api.buildPlaylistBundle(playlist.id)}` and no `playlistFilterLeftOut`. Six tests: five in `tests/test_bundles_api.py` (build and download with a round trip into a second Seek, Paused, mid-Sync, no indexed Videos, an id that isn't there) and `test_exporting_a_playlist_from_its_page_downloads_its_bundle_under_the_playlists_name` in the smoke module.

**Readings taken where the ticket left room.**
- `playlists.get_playlist(conn, id)` is new and public, the lookup ticket 01 noted was missing. It answers `Playlist {id} not found`, the sentence the module's other routes already use.
- The browser test is a test of its own, not an addition to ticket 01's. It covers what is the Playlist page's: the button, the dialog's title, count and Transcripts line, the absence of the Playlist-filter line, the suggested name, and the disabled button with its tooltip. "Building…" and a refusal shown in the dialog are the shared dialog's and stay in ticket 01's test.
- A Playlist's report always carries `playlist_filter_left_out: false`; the round-trip test asserts it.

**Not handled, and small.** As for a Channel: a Playlist whose name is exactly another Playlist's YouTube playlist id is refused as ambiguous, since the export function matches a name or an id.

**For tickets 03–06.**
- `tests/test_bundles_api.py` has `sharpening(transcripts)`: the playlist `PL-sharpening` ("Sharpening") of one Wood By Wright Video and one Rex Krueger Video. The Playlist round trip there imports the downloaded bytes with `import_bundle` directly, as the Channel's does; ticket 03 can post both to the friend's app.
- `playlists.get_playlist` is there for ticket 03's lookup of an imported Playlist's id, though that lookup is by YouTube playlist id, which it does not do.
- Ticket 06: `bundles_api.py`'s opening docstring now names both export functions.
