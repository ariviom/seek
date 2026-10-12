# 05: Limits and leftovers

**What to build:** The edges of export and import behave. A file larger than Seek accepts is refused before I send it. A file the proxy in front of Seek refuses fails with a sentence telling me to import at `localhost` or with `seek import`. An upload I walk away from is discarded, and one that has fully arrived finishes without me. A Bundle I built and never collected is deleted, and whatever a crash left in the temporary directory is cleared at the next start. Through the published host, all of it sits behind Cloudflare Access like everything else. See Spec 0006 §Import (the cap, abandoned uploads), §Export (the expiry), §Temporary files, §Web UI: Import (the fallback sentence), §Security, and §Testing Decisions.

**Blocked by:** 04 (Import waits for Syncs and for another import).

**Status:** done

- [x] An upload is capped at 2 GB, a constant the app factory takes as a parameter, as it takes its other test-tunable values.
- [x] A declared length over the cap is refused at once, without reading the body, ahead of the checks ticket 04 added. A body that passes the cap undeclared is refused and what was written is deleted. Both say: "The file is larger than 2 GB, the most the web UI imports; import it with `seek import`."
- [x] The dialog refuses a file over the cap when it is chosen, with the same sentence, before anything is sent. The page holds the same number; the server's is the one that counts.
- [x] An import failure that carries no sentence of Seek's (the response isn't Seek's JSON, or the request fails outright) shows: "The file didn't reach Seek. A proxy in front of it may refuse a file this large; import it at `localhost` on the machine Seek runs on, or with `seek import`." The page does not guess a proxy's limit in advance.
- [x] An upload the browser abandons is discarded: its directory is removed and the hold of the one import is given up.
- [x] Once the whole file has arrived, the import runs to its end whether or not the browser is still there, and its entry appears on open pages.
- [x] A built Bundle nobody collects is deleted ten minutes after it was built, with the expiry taken by the app factory as a parameter.
- [x] At start, before it serves, the server removes whatever in the temporary directory has not been modified in the last hour, and leaves what is fresher, so a second server started by mistake on the same data directory can't delete the first one's upload in flight.
- [x] Through a published host with Access configured, the build, download, and import routes need a token like any other route, and work under a forwarded prefix with one.
- [x] HTTP tests cover: a body over a small cap, both declared and undeclared, with the Library unchanged and the temporary directory empty; a built Bundle gone after a shortened expiry; and, of two leftovers planted before the app starts, the one last modified over an hour ago gone and the fresh one kept.
- [x] Two tests on a really served app, with a client that drops its connection, cover an upload abandoned partway (nothing stored, a later import accepted) and an import whose file had arrived (it completes and the entry is listed).
- [x] Tests in the remote-access tests' pattern cover the three routes without a token and with one under a forwarded prefix.
- [x] A browser test, with the upload route answered as a proxy would (a 413 with an HTML body), covers the "didn't reach Seek" sentence.

## Comments

### 2026-10-12: from ticket 01

The security review of ticket 01's commit `46dfdc6` flagged, in `src/seek/bundles_api.py`, that a built Bundle nobody collects stays on disk and in memory with no expiry (resource exhaustion, and Transcripts kept longer than they need be). That is this ticket's expiry and its clearing at start, left here by design; nothing was built for it in ticket 01.

What to hook into:
- The router's `built` map in `bundles_router` (id to `_Built(path, file_name)`), filled at the end of `build()`. An expiry pops the id from it and calls `TemporaryArea.remove(path.parent)`; `collect_bundle` already pops before it sends, so whichever comes first wins and the other finds nothing.
- `TemporaryArea.prepare()`, which the app's lifespan calls before it serves. Clearing what has not been modified in the last hour belongs there.
- The expiry and the cap reach the router through `create_app`, as its other test-tunable values do; `app_on` in `tests/test_bundles_api.py` is where the tests would pass them.

### 2026-10-12: from ticket 03

The security review of ticket 03's commit `f223c5a` flagged, in `src/seek/bundles_api.py`, that `_store` writes a request's body to the data directory's disk with no limit on its size (resource exhaustion: anyone past Access can fill the disk). That is this ticket's 2 GB cap, left here by design; nothing was built for it in ticket 03.

Where the cap hooks into `import_uploaded_bundle`:
- **The declared length.** Straight after the content-type check, which stays first, and ahead of the checks ticket 04 adds: read `Content-Length` from `request.headers` and refuse a value over the cap without touching the body. Nothing is stored before `area.new_directory()`, which comes after all of these.
- **The count while streaming.** In `_store(request, path)`, which writes each chunk of `request.stream()` as it arrives: add up the chunks' lengths and refuse once the sum passes the cap, for a body that declared no length or a false one. The handler's `finally` already removes the upload's directory, so what was written goes with it.
- Both refusals are the server's own, like the 415 beside them, so they are raised there with the status 413 and the spec's sentence; `_store` needs the cap passed in, and `bundles_router` gets it from `create_app`.

### 2026-10-12: landed on `bundles-web-ui/ticket-05`

**What landed.** In `src/seek/bundles_api.py`: `UPLOAD_CAP_BYTES` (2,000,000,000) and the refusal `_too_large`, raised for a declared `Content-Length` over the cap straight after the content-type check, and by `_body`, the one reader of a request's body, which counts what arrives for `_store` and `_discard` alike; `expire`, which a timer calls ten minutes after a build to take the Bundle out of `built` and remove its directory; and `TemporaryArea.prepare()`, which now clears what was last modified over an hour ago (`LEFTOVER_SECONDS`). `create_app` takes `bundle_upload_cap_bytes` and `built_bundle_expiry_seconds`. On the web, `useBundleImport` refuses a file over the cap as it is chosen (`tooLarge`), and `upload()` in `lib/api.ts` throws the "didn't reach Seek" sentence for a request that fails outright or an answer that carries no sentence of Seek's. Eight new HTTP tests in `tests/test_bundles_api.py`, two of them on a really served app; one in `tests/test_remote_access.py`; one browser test in the smoke module.

**The import was not moved into a task of its own, and the hold and the wake stay where ticket 04 put them.** Tickets 03 and 04 expected the request's task to be cancelled when its browser goes. It is not: uvicorn tells the app of a disconnect only through `receive`, which nothing reads once the body is in, so the handler runs on to its end, and its `finally` gives up the hold and wakes the worker when the import has ended, not before. `test_an_import_whose_file_had_arrived_runs_to_its_end_though_the_browser_has_gone_and_open_pages_are_told` passed on ticket 04's handler unchanged. It holds the import open by a write to the knowledge base from the test's own connection, as another seek process would make, drops the connection, and asserts that a second import is still refused 0.2 s later, then that the Channel is listed, the Videos-changed event is published, and a later import is accepted.

**Readings taken where the spec or ticket left room.**
- 2 GB is 2,000,000,000 bytes, a thousand to each unit, as `formatSize` and `seek export` write a size. A file of exactly that is taken; one byte more is refused.
- The sentence names the cap from the number, in the largest unit it fills, so a test's cap of 1,000 bytes reads "1 KB".
- Both of the page's sentences keep the backquotes round `seek import` and `localhost` as characters. The server can only send text, the dialog shows a sentence as it stands, and the page's copy of the cap sentence is the server's.
- A refused upload is bounded by the cap too. A body that declares no length, sent while a Sync or another import is in the way, is read no further than the cap and then answered 413, not 409: its size is what can't be waited out.
- A length declared over the cap is not read at all, so a client other than the page may see the connection reset before the sentence, as with the 415.
- In the dialog a file over the cap stays shown with its name and size ("2000.0 MB"), the sentence is the dialog's alert, and Import is disabled. Choosing another file clears it.
- The fallback sentence shows for a request that fails outright, an answer that is not JSON whatever its status (a proxy's sign-in page answers 200), and a refusal in JSON with no `detail`.
- The expiry is one timer for each build. Nothing cancels it when the Bundle is collected; it then finds nothing in the map.
- What is cleared at start is judged by the newest modification time among a leftover and everything in it. A directory's own time is when its file was created, and does not move as an upload grows, so a large file an hour into arriving would otherwise be deleted under the first server. A file lying loose in the temporary directory is cleared by the same rule. A leftover that can't be read, or that goes while it is being looked at, is skipped.
- An abandoned upload now ends as a refusal, 400 "The file stopped arriving", which nobody is there to read. Left to itself the disconnect raised out of the app, and uvicorn logged it with a traceback as a failure of the server's, once for every upload walked away from.

**Tests changed, and why.**
- `test_an_upload_the_browser_abandons_no_longer_holds_the_place_of_the_one_import` (ticket 04's) awaited the abandoned request with `asyncio.gather(..., return_exceptions=True)`, taking any ending. It now awaits it plainly, so the request has to end without raising: that is the assertion for the refusal above.
- `app_on` takes the app factory's two new parameters as `**limits`. `guarded_app` in `tests/test_remote_access.py` takes an optional `transcripts`, for an app with a Channel to build a Bundle of.
- The browser test picks a file of 2,000,000,001 bytes that is sparse, so none of it is on the disk, and answers the upload route itself: first a 413 with an HTML body, then an aborted request.

**The commit security review** found nothing in `7d9e06e` or `0376cc5`. Its record still holds the three findings of tickets 01 and 03. Two were left to this ticket and are closed by it: the built Bundle with no expiry, and the upload with no cap. The third was fixed in ticket 01.

**Not handled, and small.**
- Nothing limits how many Bundles are built inside the ten minutes. The spec accepts a forged build as a file nobody can collect, which expires; many of them at once would still fill the disk for that long.
- An upload that stalls without closing its connection keeps the place of the one import for as long as it stalls. There is no timeout on a body's arrival.
- A built Bundle is not deleted when the server stops. It goes at the first start more than an hour after it was built.
- A browser that goes in the moment between the file's last bytes reaching the server and the handler reading them is treated as having abandoned the upload: uvicorn reports the disconnect in place of the bytes it still holds. Nothing is imported and nothing is kept.
- A `Content-Length` that is not a number would answer 500. uvicorn refuses such a request before the app sees it.

**For ticket 06.**
- **README.** The cap is 2 GB (2,000,000,000 bytes) and fixed; over it the answer is `seek import`. A file a proxy turns away shows the "didn't reach Seek" sentence, which names `localhost` and `seek import`. A built Bundle waits ten minutes to be collected, once. Closing the tab during the upload discards it; closing it once the dialog says "Importing…" and the file is in does not stop the import, and the entry appears on any open page.
- **HANDOFF.** The temporary directory is `<data_dir>/tmp`, cleared at start of what is over an hour old. `create_app` takes `bundle_upload_cap_bytes` and `built_bundle_expiry_seconds`. `POST /api/bundles` now also answers 413 (over the cap) and 400 (abandoned).
- **ADR 0007's note.** The upload is counted as it is written and refused past the cap, with a declared length refused before any of it is read. The import inside the server outlives its request because the server does not cancel a request whose connection has gone, not because it runs in a task of its own; the hold of the one import and the wake of the Sync worker are the handler's.
- `bundles_api.py`'s opening docstring was left as ticket 03 wrote it; it says nothing of the cap, the expiry, or the clearing at start.
