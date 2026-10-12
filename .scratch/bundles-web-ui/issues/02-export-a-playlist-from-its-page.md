# 02: Export a Playlist from its page

**What to build:** A Playlist's page gets the same Export button and dialog as a Channel's, and my browser downloads the Playlist's Bundle as `<name>.seek`. Everything ticket 01 built for a Channel (the one-time download, the file name, the temporary directory, the dialog) is reused, not copied. See Spec 0006 §Routes, §Export, §Web UI: Export.

**Blocked by:** 01 (Export a Channel from its page).

**Status:** ready-for-agent

- [ ] The Playlist page has an Export button with the actions that concern the entry as a whole, disabled with the same tooltip when the Playlist has no indexed Videos.
- [ ] The dialog is the one the Channel page uses: titled "Export <name>", with the count of indexed Videos and the Transcripts line. It never shows the Playlist-filter line, which is a Channel's.
- [ ] Building a Playlist's Bundle is a request of the same shape as a Channel's, answering with the report and the id to collect it under. The Playlist is found by the id in the URL and the export function is given its YouTube playlist id.
- [ ] A Paused Playlist exports, and so does one whose Sync is running.
- [ ] A Playlist with no indexed Videos, and an id that isn't there, are refused as a Channel's are.
- [ ] The built Bundle is collected, named, served once, and deleted exactly as a Channel's is, through the same route.
- [ ] HTTP tests cover a Playlist's build and download, a Paused Playlist, no indexed Videos, and an id that isn't there, with the temporary directory empty after each.
- [ ] A browser test, or an addition to ticket 01's, covers Export from a Playlist page down to the download's suggested name.
