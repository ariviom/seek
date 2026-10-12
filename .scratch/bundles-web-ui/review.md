# Branch review — 2026-10-12

Fixed point: `32239a3`. Reviewed at `fd7ac61` (tickets 01 to 06); fixes are `0361119`. Independent Standards and Spec `reviewer` agents read `git diff 32239a3...HEAD`, Spec 0006, the handoff's ten decisions, the six tickets and their comments, CONTEXT.md, and HANDOFF's conventions, each asked for everything it found. Both ran `uv run mypy` and the web typecheck clean. Before the review: 816 passed, 7 deselected.

After the fixes: 823 passed, 7 deselected; mypy clean; the web typecheck and build clean; the expiry test and the two served tests ten times in a row. Eight tests are new and one was dropped (T2).

Each finding below is marked fixed or left, with the reason for one that is left.

## Spec

Found and fixed:
- **S1. A failure inside Seek showed the "didn't reach Seek" sentence and blamed a proxy.** Both ways to one are sentences of Seek's now, through the app's table of errors, and the page is unchanged. An `OSError` while the upload's directory is made or its file written is 422 "The file could not be stored: No space left on device": the system's reason and no path, raised once the rest of the body has been read, so the browser receives it. An entry removed between the import's end and the lookup of its id is 404 "The import finished, but the Channel 'X' is no longer in the Library". Three tests, each of which was an unhandled exception before. Two of them replace one function of `bundles_api` each, since no test can fill a disk or land a removal in that moment: `_create`, with a file that refuses every write, and `import_bundle`, with one that imports and then takes the Channel out of the Library.
- **S2. A built Bundle nobody collected survived a clean stop.** `bundles_router` now returns the router and `discard_built`, which the app's lifespan calls as it stops. It deletes every Bundle still in the map: that server's own, not the whole directory, because a second server started by mistake on the same data directory stops beside the first. The test builds one, starts and stops a second app on the same data directory, collects the first's Bundle, builds another, and finds nothing held once the first has stopped.
- **S3. A `HEAD` request for a built Bundle.** The finding's cause was not what the code did. FastAPI answers no `HEAD` on a `GET` route, so the handler never ran and nothing was used up: a `HEAD` was 405, or 404 from the web UI's static mount where that is served, and the `GET` after it still downloaded the Bundle. What a download manager that probes first met was a 404 for a Bundle that was there. The route now takes `HEAD` too, answers the headers a `GET` would (the length and the file name), and leaves the Bundle to be collected, which is the behaviour the finding asked for. The test was red on the 405.
- **S4. The file name could end in a dot or a space before `.seek`.** Cut, then trimmed. A case in the file-name test: 98 characters, a dot, a space, and more.
- **S5. The expiry test was timing-sensitive.** The order changed: the Bundle collected in time is built and collected first, the one left is built last, and nothing is counted while its half second runs. The count of what was waiting is gone; what it showed, that a Bundle is not deleted at once, the collection in time shows.
- **S6. The served test of an import outliving its browser.** The harness has nothing to wait on that shows the handler holding the end of the body, so the test is as it was, with a comment on what it rests on: the upload declares its length, and the server (h11 under uvicorn, read in its source) marks the bytes that complete it as the last in the message that hands them over, so a handler that has stored the whole file never asks the connection for more, and asking is the only way it learns the browser has gone.
- **S7. Two of import's refusals were not pinned through the route.** One test, run for a damaged Bundle and for one from a newer Seek, asserts each sentence and that the friend's data directory is nowhere in the answer. Both fail when the handler stops passing `called`.
- **S8. Ticket 06's comment on a Playlist Bundle all of whose Videos are left out.** A dated correction under ticket 06's comments. The event is published, once for each creator: run this time against two apps, not read.

Left:
- **Removing a directory runs on the event loop**, where the spec keeps the upload's writes off it. Unlinking even a 2 GB file is milliseconds on the file systems Seek runs on, and moving the expiry's removal into a thread means a task where there is now a plain callback.
- **The Export dialog can't be dismissed while it builds.** The spec asks that only of the import dialog. Ticket 01 took the reading on purpose: a dialog closed mid-build leaves a download that starts with nothing on screen.
- **A wrong content type and a declared length over the cap are refused without the body being read**, so a client other than the page may see a reset connection. By design: the page never sends either.

Known gaps the tickets recorded, each judged fine as it stands: a name equal to another entry's YouTube id refused as ambiguous; a `Range` request honoured and the Bundle still deleted; no limit on how many Bundles are built within the ten minutes; no timeout on a stalled upload that holds the place of the one import; a browser gone in the instant between the last bytes and the handler reading them; the refusal that stays in the alert after its Sync has finished; the page reading only the newest fifty Syncs; a Look up in flight not disabling Import; Syncs not yet loaded leaving the path open; an upload refused for a Sync holding the place of the one import while its body is discarded.

Small and new with the fixes: a `HEAD` that arrives as the same Bundle's `GET` finishes, or as its time runs out, finds the file gone after it found the id, and answers 500 to a request that reads no body.

Checked and found correct: the content-type check runs before any of the body is read; a declared length over the cap is refused before the hold is taken; the hold is taken with nothing awaited after the check and given up only after the import's thread returns; a refused body is read no further than the cap; a dropped connection at every stage ends as a 400 with its directory removed; a built Bundle is taken from the map before it is sent, so collection and expiry can't both act; the response removes the Bundle when it breaks; an upload is a file only the user can read, in a directory only the user can enter, read by nothing but the import function; no refusal shown to the page carries a server path; the download header is safe for quotes, backslashes, line breaks, other scripts, and a name with nothing left after sanitising; the three routes need an Access token and work under a forwarded prefix.

## Standards

Found and fixed:
- **T1. Test helpers were in two places.** `bundle_config` is `harness`'s alone, and the `sender` and `friend` fixtures are in `tests/conftest.py`. `app_on` is one too, in `harness`, with no contortion: it repeats the app factory's two defaults. `altered` moved to `harness` with them, since S7's test needed it beside Spec 0005's. No assertion of `tests/test_bundles.py` changed.
- **T2. The hand-built ASGI scope for the abandoned upload.** Dropped. The one thing only it asserted, that the request ends without raising, is now the served test's: it reads uvicorn's own logger and asserts nothing was logged as an error. That assertion fails when the disconnect is left to raise.
- **T3. `bundles_api.py`'s comments.** A judgement pass. Gone: the comment on the media type, the docstrings of `bundle_file_name` and `_too_large`, the opening line of `_content_disposition`'s, the echo above the Playlist build, and in the tests the docstrings of `mode`, `emptied`, and `stored_whole`. Every comment that gives a reason stays, and each one marking a security decision stays word for word.
- **T4. The file-name pattern held U+2028 and U+2029 as literal characters.** Written as `  `, and the comment names them.
- **T5. HANDOFF's list of what `format.ts` holds** has `formatCount` and `formatSize`.
- **T7. `app_on` forwarded `**limits: Any`.** Two named parameters, with T1.
- **T8. `held`'s docstring** names uploads too.
- **T9. The Export dialog's comment** says what the Bundle will share.

Left:
- **T6. "Video" is pluralised three ways in the web.** It can't be one without changing what the page shows or adding a helper that is no simpler. `plural` writes the bare number, and both dialogs group thousands (`formatCount`), so the import report through `plural` would read "1234 Videos added, 1,000 already indexed"; grouping inside `plural` instead changes every other count the web shows. The Export dialog's sentence puts "indexed" between the count and the noun and makes the verb agree ("Video goes", "Videos go"), which no count-and-noun helper writes.
- **The lookup of an imported entry's id loads every Channel or Playlist and filters.** The import function finds its entry the same way, lines away; a query by YouTube id would be the better idiom for both and is not this branch's to introduce in one of them.
- **The two Add dialogs carry the same wiring twice.** They were twins before this branch, and the shared part is already one component.
- **The select literals in the Library's dialogs repeat**, as they did before.
- **The cap's sentence picks its unit**, so that a test's cap of a thousand bytes reads as one. Kept: the tests assert the sentence a user would read.
- **`_Built`, `BuiltBundle`, `built`, and `build` sit close together.** HANDOFF and the tickets now name them.
- **`TemporaryArea.remove` is a static method on a class with state.** It is the one place that ignores a failed removal.
- **The smoke module's `bundle` fixture is the web build**, in tests now about Bundles. The name runs through three test modules and HANDOFF ("the web bundle"); renaming it is a change of its own.
- **`upload()` repeats the shape of `request()`** with different failure rules, which its comment gives.
- ADR 0002 says all state lives in one file. The temporary directory holds no state, and ADR 0007's note covers it.

Checked and found conforming: the app factory's new parameters, the router's dependencies passed as the Syncs router's are, events published on the loop after the write, the table of errors and its exact-type comment, `called` and the Playlist-name refusal in the Bundle functions, no `any` in the TypeScript, errors shown as the other dialogs show them, and no "pack", "archive", or "backup" for a Bundle anywhere in the diff.
