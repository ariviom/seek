# 05: Limits and leftovers

**What to build:** The edges of export and import behave. A file larger than Seek accepts is refused before I send it. A file the proxy in front of Seek refuses fails with a sentence telling me to import at `localhost` or with `seek import`. An upload I walk away from is discarded, and one that has fully arrived finishes without me. A Bundle I built and never collected is deleted, and whatever a crash left in the temporary directory is cleared at the next start. Through the published host, all of it sits behind Cloudflare Access like everything else. See Spec 0006 §Import (the cap, abandoned uploads), §Export (the expiry), §Temporary files, §Web UI: Import (the fallback sentence), §Security, and §Testing Decisions.

**Blocked by:** 04 (Import waits for Syncs and for another import).

**Status:** ready-for-agent

- [ ] An upload is capped at 2 GB, a constant the app factory takes as a parameter, as it takes its other test-tunable values.
- [ ] A declared length over the cap is refused at once, without reading the body, ahead of the checks ticket 04 added. A body that passes the cap undeclared is refused and what was written is deleted. Both say: "The file is larger than 2 GB, the most the web UI imports; import it with `seek import`."
- [ ] The dialog refuses a file over the cap when it is chosen, with the same sentence, before anything is sent. The page holds the same number; the server's is the one that counts.
- [ ] An import failure that carries no sentence of Seek's (the response isn't Seek's JSON, or the request fails outright) shows: "The file didn't reach Seek. A proxy in front of it may refuse a file this large; import it at `localhost` on the machine Seek runs on, or with `seek import`." The page does not guess a proxy's limit in advance.
- [ ] An upload the browser abandons is discarded: its directory is removed and the hold of the one import is given up.
- [ ] Once the whole file has arrived, the import runs to its end whether or not the browser is still there, and its entry appears on open pages.
- [ ] A built Bundle nobody collects is deleted ten minutes after it was built, with the expiry taken by the app factory as a parameter.
- [ ] At start, before it serves, the server removes whatever in the temporary directory has not been modified in the last hour, and leaves what is fresher, so a second server started by mistake on the same data directory can't delete the first one's upload in flight.
- [ ] Through a published host with Access configured, the build, download, and import routes need a token like any other route, and work under a forwarded prefix with one.
- [ ] HTTP tests cover: a body over a small cap, both declared and undeclared, with the Library unchanged and the temporary directory empty; a built Bundle gone after a shortened expiry; and, of two leftovers planted before the app starts, the one last modified over an hour ago gone and the fresh one kept.
- [ ] Two tests on a really served app, with a client that drops its connection, cover an upload abandoned partway (nothing stored, a later import accepted) and an import whose file had arrived (it completes and the entry is listed).
- [ ] Tests in the remote-access tests' pattern cover the three routes without a token and with one under a forwarded prefix.
- [ ] A browser test, with the upload route answered as a proxy would (a 413 with an HTML body), covers the "didn't reach Seek" sentence.

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
