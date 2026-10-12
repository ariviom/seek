# Branch review — 2026-10-12

Fixed point: `32239a3`. Reviewed at `fd7ac61` (tickets 01 to 06). Independent Standards and Spec `reviewer` agents read `git diff 32239a3...HEAD`, Spec 0006, the handoff's ten decisions, the six tickets and their comments, CONTEXT.md, and HANDOFF's conventions, each asked for everything it found. Both ran `uv run mypy` and the web typecheck clean. Before the review: 816 passed, 7 deselected.

Each finding below is marked **fix** or **left**, with the reason for one that is left. The fixes go in as one change; this file is then updated with the commit and the suite's result.

## Spec

To fix:
- **S1. A failure inside Seek shows the "didn't reach Seek" sentence and blames a proxy.** The page shows that sentence for any answer that isn't Seek's JSON, and an unhandled exception is a plain-text 500. Two ways to get one: the disk fills, or the directory can't be made, while an upload is stored; and the entry is removed between the import's end and the lookup of its id, where the import in fact completed. Both must reach the dialog as a sentence of Seek's: a refusal naming "The file" with the system's reason and no path for the first, and a sentence that says the import finished and its entry is gone for the second.
- **S2. A built Bundle nobody collected survives a clean stop.** The expiry is a timer in the process; a stop cancels it and removes nothing, and the next start keeps whatever is under an hour old. A Bundle built five minutes before a deploy then sits in the temporary directory, Transcripts and all, until some later start. On shutdown the server removes every built Bundle still waiting (story 50).
- **S3. A `HEAD` request for a built Bundle uses it up.** The framework answers `HEAD` on a `GET` route, and the handler takes the Bundle out of the map before it looks at the method, so a download manager that probes first turns the download into a 404. `HEAD` answers the headers and leaves the Bundle to be collected.
- **S4. The file name can end in a dot or a space before `.seek`.** It is trimmed and then cut to 100 characters, so the cut can expose one. Cut, then trim.
- **S5. The expiry test is timing-sensitive.** With an expiry of half a second it builds twice and downloads once before it counts what is waiting; under load the first can already be gone. A longer expiry, or the order changed, so that it can't.
- **S6. The served test of an import outliving its browser depends on the last bytes and the end of the body arriving in one read.** Make it wait on something that proves the handler has the whole body before it drops the connection, if the harness allows; otherwise say in a comment what it rests on.
- **S7. Two of import's refusals are not pinned through the route.** "The file is damaged or has been altered" and the newer-Seek refusal both take the name they are given, and no route test would notice a path coming back. A test for each, asserting the sentence and that it holds no path.
- **S8. Ticket 06's comment is wrong that a Playlist Bundle all of whose Videos are left out publishes no event.** Import records a row for each such Video, credited to its creator and included in the Playlist, before it judges it, so the creators are listed and the event is published. A dated correction under ticket 06's comments.

Left:
- **Removing a directory runs on the event loop**, where the spec keeps the upload's writes off it. Unlinking even a 2 GB file is milliseconds on the file systems Seek runs on, and moving the expiry's removal into a thread means a task where there is now a plain callback.
- **The Export dialog can't be dismissed while it builds.** The spec asks that only of the import dialog. Ticket 01 took the reading on purpose: a dialog closed mid-build leaves a download that starts with nothing on screen.
- **A wrong content type and a declared length over the cap are refused without the body being read**, so a client other than the page may see a reset connection. By design: the page never sends either.

Known gaps the tickets recorded, each judged fine as it stands: a name equal to another entry's YouTube id refused as ambiguous; a `Range` request honoured and the Bundle still deleted; no limit on how many Bundles are built within the ten minutes; no timeout on a stalled upload that holds the place of the one import; a browser gone in the instant between the last bytes and the handler reading them; the refusal that stays in the alert after its Sync has finished; the page reading only the newest fifty Syncs; a Look up in flight not disabling Import; Syncs not yet loaded leaving the path open; an upload refused for a Sync holding the place of the one import while its body is discarded.

Checked and found correct: the content-type check runs before any of the body is read; a declared length over the cap is refused before the hold is taken; the hold is taken with nothing awaited after the check and given up only after the import's thread returns; a refused body is read no further than the cap; a dropped connection at every stage ends as a 400 with its directory removed; a built Bundle is taken from the map before it is sent, so collection and expiry can't both act; the response removes the Bundle when it breaks; an upload is a file only the user can read, in a directory only the user can enter, read by nothing but the import function; no refusal shown to the page carries a server path; the download header is safe for quotes, backslashes, line breaks, other scripts, and a name with nothing left after sanitising; the three routes need an Access token and work under a forwarded prefix.

## Standards

To fix:
- **T1. Test helpers are in two places.** `bundle_config` is the same in the harness and in Spec 0005's test module, and the `sender` and `friend` fixtures are in both Bundle test modules. One copy of each; `app_on` too if the two can be one without contortion, and say so if not.
- **T2. One test drives the app with a hand-built ASGI scope**, off the harness HANDOFF names as the HTTP seam, for the abandoned upload that a served test also covers. Drop it, with anything only it asserted moved into the served test.
- **T3. `bundles_api.py` is commented at several times its neighbours' density**, and a number of its docstrings and comments, and of the new test helpers', narrate what the code does. Keep the ones that give a reason, the security ones above all; remove the rest.
- **T4. The file-name pattern holds U+2028 and U+2029 as literal characters**, invisible in an editor and unmentioned in the comment. Write them as escapes and name them.
- **T5. HANDOFF's list of what `format.ts` holds** lacks `formatSize` and `formatCount`.
- **T6. "Video" is pluralised three ways in the web** (`plural`, a local helper in the import path, an inline form in the Export dialog). One way, if it can be had without changing a word the page shows; otherwise leave it and say so.
- **T7. The API tests' `app_on` forwards `**limits: Any`.** Two named parameters.
- **T8. `held`'s docstring** says it lists built Bundles; it lists uploads too.
- **T9. A comment in the Export dialog says "an export"** for the file, which the glossary avoids.

Left:
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
