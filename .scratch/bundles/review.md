# Branch review — 2026-10-11

Fixed point: `e3872f6`. Reviewed at `5bbed32` (tickets 01 to 06 and a README correction); fixes are `39c1b2e`. Independent Standards and Spec `reviewer` agents read `git diff e3872f6...HEAD`, Spec 0005, the six tickets and their comments, `ticket-01-review.md`, CONTEXT.md, and HANDOFF's conventions, each asked for everything it found. The Spec agent ran the suite (748 passed, 7 deselected; mypy clean) and probed 39 hand-built hostile files, each refused with one `seek:` sentence and no data directory created. It also interrupted a 4,000-Video import: the lease was released and the second run reported 3,998 added, 2 already indexed.

After the fixes: 753 passed, 7 deselected; mypy clean; the six lease tests ten times in a row.

## Spec

Found and fixed:
- **A renewal that only timed out was reported as another process taking over.** The background thread treated any `sqlite3.Error` as a lost lease. Import still stops before its next Video, and now says the knowledge base was too busy to keep its hold on Syncs. The "another seek process took over" sentence is kept for a lease that really went elsewhere.
- **The per-Video renewal could be a traceback** (`database is locked` on the main connection). It is the same busy sentence now.
- **Ctrl+C in `seek import` printed a stack trace**, on the command the spec invites interrupting. It exits non-zero with `seek: The import was interrupted; run it again to carry on where it stopped`. A second Ctrl+C while the renewal thread was being joined skipped the lease's release; the release always runs now.
- **A Bundle with no Videos imported and created an empty entry.** Export never writes one, so it is refused as damaged.
- **An avatar was held to its host and nothing else**, so one of 500,000 characters, or with a newline or ESC after the host, was stored. It is dropped unless it is also at most 2,000 characters with no control characters or whitespace.
- **A Transcript with no lines passed beside a Video with Segments.** Refused. No lines and no Segments stays valid: it is what a Sync stores for blank captions.
- **NUL passed in what was said.** Refused in every text field. `datetime.fromisoformat` accepts a trailing NUL, so timestamps refuse it themselves.
- **Playlist export's refusals were asserted nowhere.** Tests added for no indexed Videos (and no file left), an unknown name, and an ambiguous one.
- ADR 0007's meta record omitted the Seek version and the export time.

Spec text the code no longer matches, left for Drew to amend or not:
- §Export, "On the recipient's machine the Channel's filters will exclude those at the next Sync": §Import has a new Video judged by the date range at import, and the code follows §Import (ticket 03's reading). The sentence holds only for the most-recent count.
- §Import, a Playlist Bundle's Video "judged exactly as a Playlist Sync's discovery judges one it includes": a Video that is `done` and searchable is not judged, so an import never changes one (ticket 04's reading, story 27). Discovery would judge it.

Recorded readings checked and left as they are:
- Import renews the lease before each Video as well as from the background thread (ticket 05).
- `--name` is validated before the file is opened, so a bad one is refused even when the entry exists and the name would go unused (ticket 03).
- A name holding a bidi embedding, override, or isolate is refused, and export does not warn of it (ticket 02, ADR 0007).
- `_import_video`'s write refuses a row that is `done`, excluded, or credited to another Channel, by raising. No seam reaches it (ticket 03).
- A Playlist Bundle records a new Video under the minimum length as an excluded row the Playlist includes, where a Channel Bundle writes nothing for one (ticket 04).
- A creator listed and unused is ignored; two Videos may share a position until the next Sync (ticket 04).
- The lease tests write and read `sync_lease` directly to hold and time the lease (ticket 05). The server test shortens `LEASE_SECONDS` to 2 and is the one test here that depends on a thread running within about a second and a half.

Not checked: a single Video whose own transaction outlasts the busy timeout, and the renewal thread failing to open its connection (import would carry on with the per-Video renewals).

The five items accepted with an unsigned Bundle (tickets 02, 03, 04; ADR 0007) were checked against the code and the docs, not reopened. All five are in ADR 0007.

## Commit security reviews

A review ran after each commit. Fixed in their tickets: text fields with no length bound (02), exclusions not yet applied on merge (03, the ticket's own unfinished rule at a checkpoint). Acknowledged as the spec's behaviour and recorded in ADR 0007: invisible characters reaching a chat model; a Segment's `context` and text unchecked against the Transcript (`context` is in the lexical index); a Bundle completing an unfinished Video under the Channel it is credited to here; a Bundle's name and avatar on a Channel known only outside the Library; a Playlist Bundle lifting a Channel-filter exclusion. The names rule was narrowed during 02 from all format characters to the bidi ones, so that a real YouTube name with a joined emoji or a flag sequence still imports. The final commits of ticket 04 and the review fixes came back clean, and no finding was recorded for ticket 05's.

## Standards

Found and fixed:
- HANDOFF's conventions still said neither Channels nor Playlists can be added from the CLI, and that `channels.create_channel` brings a creator in unfiltered. Both corrected, and a conventions bullet added for the Bundle commands.
- `_meta` tested `"meta" not in plain` after a line that had already raised for it.
- `cli.export` used `assert channel is not None` to choose a branch. `main` now passes it the export function.
- A test filtered raw `videos` rows by tuple membership over every column; it filters on the YouTube id column.
- The two new CLI tests each defined their own `run`; one module-level helper serves both.
- Small: redundant `isinstance` checks, `fromisoformat(...) is not None`, a positional `None` for `name` in `to_thread`, a `no-bundle` directory name for the web bundle, a comment that `LEASE_SECONDS` is read at call time, and "pack" quoted in ADR 0007 as MVP §4's word.

Left as judgement calls:
- `import_bundle` branches on the Bundle's kind four times across about 120 lines, each branch binding locals a later one reads.
- `bundles.py` imports `FiltersBody` from `channels_api` for the filters' ranges, and repeats the YouTube id pattern and the 200-character name length that `channels_api` and `fields` hold.
- Validated rows travel as `dict[str, object]` and are cast back where they are used.
- `export_channel` and `export_playlist` each spell out the "searchable Video" condition.
- `tests/test_bundles.py` is 1,860 lines across five concerns, and its `lease()` helper could sit in the harness.
- ADR 0007 runs longer than its siblings.
- Names: `_contents`, `rows` used to run statements, `listed` for two different things, `uncredited` passed as a message fragment, `Kind` beside `videos.Source.kind`.

`tests/test_doctor.py` carries a change that is not Bundles work (`d937e0b`): the installed-service test now has a config directory of its own. Drew asked for it in this session; the handoff's "leave both alone" predates that.

Clean: glossary terms across code and docs, the tracker's conventions, tests through the app's surfaces with no fixed sleeps, ADR 0007's headings and status line, mypy strict.
