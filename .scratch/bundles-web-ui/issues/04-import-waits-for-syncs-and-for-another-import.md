# 04: Import waits for Syncs and for another import

**What to build:** While a Sync is running or queued, the import path in the Add dialogs is disabled and says why, so I never upload a large file only to be refused. If a Sync starts in between, or another import is under way in a second tab, the server refuses on its own and the sentence reaches the dialog. A Sync I queue while an import runs starts as soon as the import ends. See Spec 0006 §Import (the ordered checks, and the last point), §Web UI: Import, and the Further Note "What refusing on a queued Sync costs".

**Blocked by:** 03 (Import a Bundle from the Add dialogs).

**Status:** done

- [x] While any Sync is running or queued, the import path is disabled and says so beside it: "A Sync is running or waiting to run; import when it has finished." The Syncs already held live at the top of the app are passed down to the dialogs.
- [x] The server refuses an import while a Sync is running or queued, with the same sentence, before anything is stored.
- [x] A server runs one import at a time. A second, while one is uploading or importing, is refused before anything is stored: "Another import is running; try again when it has finished."
- [x] The hold of the one import is given up however that import ends: completed, refused, failed, or its upload abandoned. A later import is then accepted.
- [x] An upload refused for either reason is still read to its end and discarded, so the browser receives the sentence and not a dropped connection.
- [x] The Sync lease stays the backstop: a Sync that starts after the check still refuses the import, with the command's sentence.
- [x] When an import ends, however it ends, the server wakes its Sync worker.
- [x] A queued Sync refuses for as long as it stays queued, which while the embedding model loads or a YouTube throttle is waited out can be a long time. This follows from the grilling session's decision 6 and is not to be softened; `seek import` is still refused only by a Sync that is running.
- [x] HTTP tests cover, each asserting the sentence and that the Library is unchanged: a Sync running (held by a `Gate`), a Sync queued, and another import running, the first held open by a request body that pauses before its last chunk. A later import is accepted once that first request has ended, either way.
- [x] An HTTP test covers a Sync queued while an import ran starting without waiting for the poll, with the app given a long poll interval so that only the wake can explain it.
- [x] A browser test covers the import path disabled with its reason while a Sync is held by a `Gate`, and enabled again once it finishes.

## Comments

### 2026-10-12: landed on `bundles-web-ui/ticket-04`

**What landed.** In `import_uploaded_bundle` (`src/seek/bundles_api.py`), between the content-type check and `area.new_directory()`: an import under way refuses a second with "Another import is running; try again when it has finished.", and `syncs.has_work` (a Sync running or queued) refuses with "A Sync is running or waiting to run; import when it has finished." Both are a `Conflict` (409), and both read the body to its end first, through `_discard`. The hold of the one import is `importing`, a flag in the router, given up in a `finally` that also wakes the Sync worker; `bundles_router` takes the worker's `wake` as `syncs_router` does. On the web, `useBundleImport(imports, syncs)` works out `syncing` with `isRunning` from `lib/sync-status.ts`, and `ImportBundle` disables the picker and the Import button on it and shows the sentence under the picker; `syncs` comes from `App.tsx` through `useLibraryDialogs` to both dialogs. Six new HTTP tests (seven cases) in `tests/test_bundles_api.py` and one browser test in the smoke module.

**Readings taken where the spec or ticket left room.**
- The order is the spec's: the one import first, then Syncs. An upload refused for a Sync holds the place of the one import until its body has been read, so a second sent meanwhile is told "Another import is running".
- The worker is woken whenever an import the server took on ends, one refused for a Sync included. A second import refused for the first is not an import that ended, and wakes nothing.
- **The test of the wake queues its Sync straight into the knowledge base, as another seek process would, while the file is still arriving.** A Sync queued through the route at that point starts at once, since nothing holds the lease yet, and then the lease refuses the import: that is the backstop's test. A Sync queued through the route while the import function holds the lease is the case the wake exists for, and the HTTP seam has no way to hold an import there: the function is called with no progress callback, and a small Bundle is in within milliseconds. Queued behind the server's back, the Sync wakes nothing itself, so with an hour between polls only the import's end explains its start. Without the wake the test times out.
- The Sync held queued is one waiting for the embedding model, loading behind a `Gate`: the case the spec's Further Note names. Nothing can be searched while the model loads, so that test compares the Syncs before and after the refusal and looks at the Library once the model has loaded.
- The backstop is tested too (`test_a_sync_that_starts_while_the_file_is_still_arriving_...`): it answers 422 with "A Sync is running; run the import again when it has finished", the command's words, which no code here changed.
- An abandoned upload is tested in-process, by a `receive` that answers `http.disconnect` in place of the last chunk: the hold is given up and the directory removed. That is not ticket 05's test on a really served app, which is still to write.
- On the page, Syncs not yet loaded leave the path open; the server is what counts. A file already chosen stays chosen while the path is disabled, with its Import button disabled. The sentence is muted text under the picker, not an alert.

**Tests changed.** None of the existing ones. `app_on` takes an optional `sync_poll_seconds`.

**The commit security review** was started for `734fea7` and `14740f2` and reported nothing in the three and a half minutes after them; its record still holds only the three findings of tickets 01 and 03, each already fixed or with ticket 05.

**Not handled, and small.**
- A refusal the server sent stays in the dialog's alert after the Sync that caused it has finished, until a file is chosen or Import is pressed; while the Sync lasts the same sentence shows twice, as the note and as the alert.
- The page reads the newest fifty Syncs, which is what `GET /api/syncs` lists. A Sync still queued behind fifty newer ones would leave the path open, and the server would refuse.
- An upload abandoned while it is being discarded or stored raises `ClientDisconnect` out of the handler, as it did before this ticket.

**For tickets 05 and 06.**
- **05, the cap.** The declared length is checked straight after the content-type check and ahead of `if importing`, so a file over the cap is refused without taking the place of the one import and without being read.
- **05, a refused upload has no cap either.** `_discard` reads to the end whatever the length, storing nothing. A body of no declared length sent while a Sync runs is read for as long as it keeps coming; if the cap should bound that too, the count belongs in `_discard` as it does in `_store`.
- **05, an import outliving its request.** `importing` is given up, and the worker woken, in the handler's outer `finally`. Once the import, the lookup, and the publishing move into a task of their own, that `finally` has to move with them: left on the request, a browser that goes away after the file has arrived would free the place of the one import while that import is still running, and wake the worker while the lease is still held.
- **05, an abandoned upload.** It already gives up the hold and removes its directory; what is left is the test on a really served app.
- **Tests.** In `tests/test_bundles_api.py`: `wrights_bundle(sender, transcripts)` (a one-Video Bundle of Wood By Wright), `Paused(content)` with `sent_to(client)`, `arriving`, and `let_go` (the body that pauses before its last chunk), `in_halves(content, read)` (a body that notes how much of it the server asked for), `AS_A_FILE`, `SYNC_IN_THE_WAY`, and `ANOTHER_IMPORT`.
- **06.** The README and the ADR note have two things to say that the command doesn't share: in the web UI an import waits for a Sync that is queued as well as one that is running, and a server runs one import at a time. `bundles.py`'s docstring says a Sync queued during an import "waits for it"; inside the server it now also starts when the import ends, not at the next poll.
