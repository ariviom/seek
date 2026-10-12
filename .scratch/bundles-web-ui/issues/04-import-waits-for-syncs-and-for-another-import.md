# 04: Import waits for Syncs and for another import

**What to build:** While a Sync is running or queued, the import path in the Add dialogs is disabled and says why, so I never upload a large file only to be refused. If a Sync starts in between, or another import is under way in a second tab, the server refuses on its own and the sentence reaches the dialog. A Sync I queue while an import runs starts as soon as the import ends. See Spec 0006 §Import (the ordered checks, and the last point), §Web UI: Import, and the Further Note "What refusing on a queued Sync costs".

**Blocked by:** 03 (Import a Bundle from the Add dialogs).

**Status:** ready-for-agent

- [ ] While any Sync is running or queued, the import path is disabled and says so beside it: "A Sync is running or waiting to run; import when it has finished." The Syncs already held live at the top of the app are passed down to the dialogs.
- [ ] The server refuses an import while a Sync is running or queued, with the same sentence, before anything is stored.
- [ ] A server runs one import at a time. A second, while one is uploading or importing, is refused before anything is stored: "Another import is running; try again when it has finished."
- [ ] The hold of the one import is given up however that import ends: completed, refused, failed, or its upload abandoned. A later import is then accepted.
- [ ] An upload refused for either reason is still read to its end and discarded, so the browser receives the sentence and not a dropped connection.
- [ ] The Sync lease stays the backstop: a Sync that starts after the check still refuses the import, with the command's sentence.
- [ ] When an import ends, however it ends, the server wakes its Sync worker.
- [ ] A queued Sync refuses for as long as it stays queued, which while the embedding model loads or a YouTube throttle is waited out can be a long time. This follows from the grilling session's decision 6 and is not to be softened; `seek import` is still refused only by a Sync that is running.
- [ ] HTTP tests cover, each asserting the sentence and that the Library is unchanged: a Sync running (held by a `Gate`), a Sync queued, and another import running, the first held open by a request body that pauses before its last chunk. A later import is accepted once that first request has ended, either way.
- [ ] An HTTP test covers a Sync queued while an import ran starting without waiting for the poll, with the app given a long poll interval so that only the wake can explain it.
- [ ] A browser test covers the import path disabled with its reason while a Sync is held by a `Gate`, and enabled again once it finishes.
