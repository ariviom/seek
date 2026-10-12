# 06: Document Bundles in the web UI

**What to build:** Someone reading the README learns that a Channel or Playlist is shared from the web UI first, and from the command line second, and what to do when a proxy refuses a large Bundle. The next agent reading HANDOFF finds the routes and the temporary directory in the conventions. ADR 0007 says that import now also runs inside the server. See Spec 0006 §Docs.

**Blocked by:** 02 (Export a Playlist from its page), 05 (Limits and leftovers).

**Status:** done

- [x] The README's "Sharing a Channel or Playlist" leads with the web UI: Export on the entry's page, and import in the Add Channel and Add Playlist dialogs, either kind in either. The two commands stay, after it.
- [x] It says a large Bundle may be refused by a proxy in front of Seek, and that such a file imports at `localhost` on the machine Seek runs on, or with `seek import`. It gives the 2 GB cap of the web UI. It does not state a proxy's limit as fact: Cloudflare's 100 MB is unverified.
- [x] "Publishing through a reverse proxy" gets a line on the same.
- [x] Wherever the README says a Channel or Playlist arrives only by the web UI's Add or by `seek import`, it now reads true.
- [x] HANDOFF gets a dated update entry for Spec 0006, and its conventions name the Bundle routes, the temporary directory and when it is cleared, the one-import-at-a-time hold, and the two changes to the import function.
- [x] ADR 0007 gains a dated note, not a successor: import also runs inside the server, on an uploaded file, in a worker thread, under the same lease, so the second writer is either the CLI's process or a thread of the server's. The untrusted file now also arrives over HTTP, and the note records the content-type requirement, the cap, and that it is never held in memory.
- [x] CONTEXT.md is unchanged, and nothing written here uses "export" as a noun, "pack", or "archive" for a Bundle.
- [x] Each sentence about behaviour is checked against the code as it landed, not against the spec, and anything of the spec the code no longer matches is brought in line and named in this ticket's comments.

## Comments

### 2026-10-12: landed on `bundles-web-ui/ticket-06`

**What changed.** Docs, and two module docstrings; no behaviour.
- `README.md`. "Sharing a Channel or Playlist" now opens with the web UI: Export on the entry's page, import in the Add channel and Add playlist dialogs, then the ways an import there differs from the command (it waits for a queued Sync as well as a running one, one import at a time, the web wording of the Playlist-name refusal, the 2 GB cap, a proxy that turns a large Bundle away, and what closing the tab does). The commands follow under "From the command line", and the sentences below them that were true of the command alone now say `seek export` or `seek import`. "Publishing through a reverse proxy" has a fifth step on the request body. The sentence under `seek sync` that said a Channel or Playlist is added in the web UI or imported with `seek import` now has the web UI adding from YouTube or from a Bundle. First run points a friend with a `.seek` file at the dialogs, the Contents line names both ways, and Data lists `tmp/`.
- `HANDOFF.md`. A dated update for Spec 0006 under Historical progress. In the conventions: a new "Web Bundles" entry (the four routes and their statuses, the order of the import's checks, the hold of the one import and the wake, the temporary directory and its clearing at start, the web modules, the tests); "CLI Bundles" has the `called` parameter and `PlaylistNameTaken`, and no longer says none of the three goes through the server; `create_app`'s two new parameters; `channels.get_channel`, public since ticket 01; the smoke module's twelve tests.
- `docs/adr/0007-…md`. A note dated 2026-10-12 appended: the second writer, the server's two refusals ahead of the lease, why the import outlives its request, and the content type, the cap, and the streaming to disk.
- `src/seek/bundles.py`'s opening docstring says the commands run in the CLI's own process and that the server calls the same functions. `src/seek/bundles_api.py`'s now names the cap, the one import, the expiry, and the clearing at start.

**Spec sentences brought in line with the code.** The ten Decisions and the design are untouched.
- §Routes: the statuses gain 400 for an upload that stopped arriving, and say a build answers 201.
- §Import, the refused upload: it is read no further than the cap, so an undeclared body that passes it while being discarded answers 413, not 409.
- §Import, the cap: 2 GB is 2,000,000,000 bytes.
- §Import, the abandoned upload: its request ends as 400 "The file stopped arriving"; and the import outlives its request because the server does not cancel a request whose connection has gone, with no task of its own (ticket 05's comment has the reason).
- §Further Notes, the import that loses its hold on Syncs: the command has two sentences for it, and the note named only "Another seek process took over running Syncs"; a renewal that fails says "The knowledge base was too busy for the import to keep its hold on Syncs".
- §Further Notes, a proxy's wait: a build that outlasts it does not show the fallback sentence. `api.buildChannelBundle` and `buildPlaylistBundle` go through the shared `request`, so the Export dialog shows "Request failed (status)". Only an import shows the "didn't reach Seek" sentence.
- Ticket 03's opening paragraph cited "§Two small changes to the Bundle functions"; it now says three, as the spec's heading does.

**Readings taken.**
- The README says a proxy "may limit" an upload and names no number. It names nginx's `client_max_body_size` as the setting to look at, which is a name and not a limit.
- The README gives `http://localhost:7337` for importing on the machine Seek runs on, "unless you changed the port".
- "The two changes to the import function" are `called` and `PlaylistNameTaken`.
- The spec's `Status:` line is left as it was; the whole-branch review is still to come.

**Found in the code and left alone.**
- A Playlist's Bundle all of whose Videos are left out here (each under the minimum length) adds a Playlist with no Videos, and `videos.listed_by_creator` then lists no creator, so no Videos-changed event is published: other open pages show that Playlist only at their next reload. Read from the code, not run.
- `Config.temporary_dir`'s comment says the directory is where a Bundle is held "while it is built and until it is collected"; it holds uploads too.
- `import_bundle`'s docstring says a Sync queued meanwhile "waits for it", which is true, and does not say that inside the server it then starts at once.

**Verification.** `uv run pytest -q`: 816 passed, 7 deselected. `uv run mypy`: clean. Nothing under `web/` changed.

### 2026-10-12: a correction, from the whole-branch review (S8)

The first item under "Found in the code and left alone" above is wrong. A Playlist's Bundle all of whose Videos are left out here does publish the Videos-changed event, once for each creator, and other open pages show the Playlist at once.

Import records a row for each such Video before it judges it: credited to its creator, excluded for its length, and included in the Playlist (`bundles.py`, the function that has the Playlist include a Bundle's Video). `videos.listed_by_creator` lists a Playlist's creators from those rows whether or not they are excluded, so it lists both. Run this time, not read: a Bundle of the Playlist "Sharpening", two Videos of two creators, imported into a Seek with a 720 second minimum, reports `added: 0` and `left_out: {"Shorter than the 720 second minimum": 2}`, and the event stream carries `{"type": "videos", "channel_id": …, "playlist_ids": [1]}` for each of the two. The Playlist is listed with no indexed Videos, two excluded, and both creators. There is no gap here to hand on.
