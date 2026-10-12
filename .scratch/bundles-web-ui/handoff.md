# Handoff — Bundles in the web UI

Drew and I shaped this in a grilling session on 2026-10-11, after Spec 0005 shipped (`main` at `176c9ac`, deployed and pushed). The ten decisions below are his; don't reopen them. What is left is the spec (0006), its critique, and the build. This file is untracked in `/home/drew/mentor`: commit it with the spec.

## What to build
Export and import of Bundles from the web UI, the piece Spec 0005 listed as out of scope. The Bundle format, validation, merge rules, and the two CLI commands do not change; the server calls the same functions in `src/seek/bundles.py`.

## Decisions
1. **Both kinds.** Channels and Playlists each get Export. Import takes a Channel Bundle or a Playlist Bundle.
2. **Reach.** Both features work wherever the UI does, including through the published host behind Cloudflare Access. Import is one plain upload with no chunking. A file the proxy rejects fails with a sentence saying to import at `localhost` or with `seek import`.
3. **Export is a browser download.** The server builds the Bundle in a temporary file, sends it as `<name>.seek`, and deletes the temporary file.
4. **Export sits on the entry's page**, with Sync now, Filters, Rename, Pause, and Remove. Not in the Library's rows, which carry no actions.
5. **Import sits in the Add dialogs**, as a second path ("or import a `.seek` file") in Add Channel and in Add Playlist. No Import button elsewhere.
6. **Import while a Sync is running or queued is refused.** The option is disabled and says why, so nothing is uploaded only to be refused. The server still refuses on its own if a Sync starts in between.
7. **No name field.** The entry takes the Bundle's name; Rename is on its page. While it works the dialog shows "Importing…" with no per-Video count. Then it shows the report (added, already indexed, left out with reasons, the "only as trustworthy as whoever made it" line) with a "Start a Sync" button, and selects the entry.
8. **Either dialog accepts either kind**, imports it, and selects what arrived. The report names the kind.
9. **Export opens a confirm dialog**: the entry's name, its count of indexed Videos, the line that the file contains the creators' full Transcripts, and for a Channel with a Playlist filter the note that the filter is left out. One "Export" button, then "Building…" until the download starts.
10. **Export is disabled, with a tooltip, on an entry with no indexed Videos.**

Refusals show in the dialog as the sentences the CLI prints.

## Facts already gathered (don't re-explore)
Web:
- Library list: `web/src/library/LibraryList.tsx:66-132`; rows `ChannelList.tsx:16-53`, `PlaylistList.tsx:16-57`, each one select button (`shell/ListRow.tsx:5-27`).
- Entry pages and their actions: `library/ChannelPage.tsx:46-229`, `library/PlaylistPage.tsx:43-210`. Routing `LibraryMain.tsx:140-216`.
- Add dialogs: `library/AddChannelDialog.tsx:15-124` (URL, "Look up", name, "Add"; errors as an `Alert` at :104-108), `library/AddPlaylistDialog.tsx:140-250`. Success selects the new entry (`library/Library.tsx:33-36`).
- API calls: `web/src/lib/api.ts:285-298` `request<T>()`, JSON only, throws `Error(detail)`. Mutations go through `useChanges` (`lib/changes.ts:9-32`). Nothing in `web/src` uploads a file or triggers a download today.
- Live state: one `EventSource("api/events")` (`lib/events.ts:34`); `useLiveList` reloads on `ready` (:91-133); Syncs from `syncs/useSyncs.ts:30-33`, running preferred over queued in `lib/sync-status.ts:31-42`.
- UI kit in `web/src/components/ui/` has dialog, button, alert, tooltip. There is no toast; feedback is an inline `Alert` or `shell/Notices.tsx`.
- No web unit tests. Browser tests are Python Playwright in `tests/test_smoke.py` (`serving()`, `browsing()`).

Server:
- `import_bundle(config, path, name=None, progress=None) -> ImportReport` (`bundles.py:459`); `export_channel` / `export_playlist(config, name, path) -> ExportReport` (:227, :268). Each opens its own connection, so a handler runs them with `asyncio.to_thread`, not `database.run`.
- Export writes `<name>.seek.<rand>.tmp` with `mkstemp` beside the destination and renames it (:377, :348), so the handler chooses the directory.
- The lease: an idle server holds none (`sync_worker.py:107-111`), so an in-process import coexists with the worker and is refused only while a Sync runs ("A Sync is running…", `bundles.py:597`). While import holds it, a queued Sync waits for the worker's poll.
- Errors: `ERROR_STATUS` in `app.py:58-67` maps `NotFound` and `Conflict` to `{"detail": …}`. `SyncCommandError`, which every Bundle refusal raises, is not mapped.
- Events are published from the event loop only (`events.py:28`), so not from the import's thread.
- Access: `ProxyMiddleware` (`proxy.py:38-81`) rejects a foreign Host or Origin, checking Origin only when present. `AccessMiddleware` (`access.py:118-146`) requires the Cloudflare assertion for anything not direct from loopback. There is no CSRF token, no loopback-only route, and no request-body size limit.
- `python-multipart` is not a dependency (transitive through `mcp` only). Raw bodies are read in `settings_api.py:20`, `storyboards_api.py:44`, `credentials_api.py:32`.
- API tests use the `client` fixture (`tests/conftest.py:65-92`) over `harness.running()`; example `tests/test_channels.py:44`.

Measured on the reference Library: its largest Channel (898 Videos, 23,919 Segments) is a 255 MB Bundle, 15 s to export and 23 s to import. Not verified: that Cloudflare caps an upload at 100 MB on this plan.

## For the spec to settle (my recommendations, not Drew's decisions)
- Send the file as a raw request body (`application/octet-stream`), streamed to a temporary file, never held in memory. It needs no new dependency, and a non-form content type cannot be sent cross-site without a preflight.
- Where temporary files live (uploads and Bundles being built), that they are deleted on every path, and what clears ones a crash left.
- Map `SyncCommandError` to a status with the sentence as `detail`.
- Return the reports as JSON for the dialog to render, since "Start a Sync" replaces the CLI's `seek sync --channel ID` line.
- Publish what the Library needs to reload after an import, from the event loop once the thread returns.
- The download's file name: an entry's name can hold any character.
- Whether an upload needs a size cap, now that a remote user past Access can send one.
- ADR 0007 says import is a CLI command writing beside a running server. The server now imports an uploaded file itself: amend the ADR or add a note.
- Docs: the README's "Sharing a Channel or Playlist" section and HANDOFF's conventions.

## How to work
As `.scratch/bundles/handoff.md` describes for Spec 0005: the spec's seams, `tdd`, `uv run pytest -q && uv run mypy`, the commit security review after each commit, and a `reviewer` critique of the spec before any code. This one touches `web/`, so a fresh worktree needs `pnpm --dir web install --frozen-lockfile`, and the web typecheck and build must pass.
