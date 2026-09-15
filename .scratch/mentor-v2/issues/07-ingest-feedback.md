# 07 — Ingest feedback: live sync status everywhere, "index" out of the UI

**What to build:** Show a running Sync's progress wherever its Channel appears, with a rate and time remaining that survive a reload, and stop the UI conflating a Sync (one ingest run) with a Channel's `indexed` flag (whether it takes part at all). Decided with Drew on 2026-09-14: the flag reads **Active / Paused**; there is still no stop endpoint (spec 0002 §Syncs stands).

**Blocked by:** nothing (05 is done; 06 can follow or precede)

**Status:** done

Why: the first real ingest (553 Videos) gave one recoloured bar on the Channel page, "never synced" in the Library row, and "Fetching …" only on the Syncs page. The card was titled "Indexing" with "Stop indexing" next to "Sync now", so the flag read as the way to stop the run; the log shows it being toggled during the Sync. A Sync at YouTube's pace takes ~15 s per Video, so a first ingest is hours; the user needs to see it moving and know when it ends.

Backend
- [x] `Sync.completed_videos`: Videos that reached done or failed during this Sync. Migration 10 (additive string entry) adds `completed_videos INTEGER NOT NULL DEFAULT 0` to `syncs`; `syncs.update_progress` increments it when `_progress` is called with a Video whose stage is now done or failed (pass a flag from `_advance`; a Video counted once). Serialised on every Sync shape and event. A Sync's rate is `completed_videos / (now − started_at)`; remaining is `stage_counts.discovered + transcript_fetched + segmented + embedded`.
- [x] Tests: `test_sync_events.py` sees `completed_videos` climb on the streamed `sync` events and land at the finished count; migration 10 on a schema-9 database in `test_migrations.py`.

Web: vocabulary
- [x] The `indexed` flag is shown as **Active / Paused** and nothing in the UI says "index". Channel page: a status badge in the header ("Paused" when not `indexed`); the footer button reads "Pause channel" / "Resume channel"; a one-line hint under it: "A paused channel isn't synced and doesn't answer; what's ingested stays." The New chat hint and `scope.ts` `unavailable` message say "paused" not "not indexed". The "Indexing" card is titled **Videos**; its first line is the status line below. `n videos` in rows and member lists means ready to answer (`indexed_videos`, unchanged).
- [x] `CONTEXT.md` "Decisions reflected in the language": "Excluding a Channel from syncs, search, and chats is done on the Channel (pause it), not per Group." README's `mentor list` line and `--all` comment say active. The API field stays `indexed`; the CLI's wording follows README.

Web: live status
- [x] `lib/sync-status.ts`: `syncProgress(sync, now)` → `{ label, completed, total, remaining, secondsLeft | null, fetching }` from the Sync record (`completed_videos`, `started_at`, `stage_counts`, `fetching`), and `useNow(seconds)` ticking only while a Sync is queued or running so the estimate counts down. Text: "Syncing · 23 of 553 ready · about 2 h left · fetching “…”" (rate needs ≥ 3 completed Videos before an estimate is shown; "Queued" while queued; the error line when failed).
- [x] Shown on: the Channel page's Videos card (replacing "All videos · last synced …" while a Sync is queued or running, with a link to the Sync page; the stage rule stays underneath); the Library Channel row (`Syncing 23/553` with the compact rule, instead of "never synced"); the Syncs row and page (page adds the estimate to its status line); the New chat members card and the Composer's note when a member Channel is mid-Sync ("answers use the 23 videos ready so far"). The rail dot stays.
- [x] Sync all / Sync now on a Channel that already has a queued or running Sync: the button says "Syncing…" and is disabled. `syncs.enqueue` returns the Sync already queued for the Channel, but a Channel whose Sync is *running* gets a second one queued behind it (Sync 3 on 2026-09-14 was that); either is a no-op worth preventing in the UI.

Verify
- [x] Typecheck and build; `uv run pytest -q`; `test_smoke.py` asserts the Library row and Channel card show the Sync moving ("Syncing", then "1 video · synced …"); throwaway Playwright script against a `Gate`-held fetch: status line with fetching title on Channel page, Library row, Syncs page; reload keeps the estimate; pause a Channel and read the badge and hint; the "index" word absent from the DOM.

From ticket 07 review (deferred)
- `remaining` follows the ticket formula (discovered + transcript_fetched + segmented + embedded), so Videos failed in an earlier Sync that a retry re-runs are not in `total` until they finish: a retry of 3 failed Videos reads "0 of 2 ready" then "3 of 3 ready". Count `failed` into `remaining` on a retry-failed Sync if that reads wrong in use.
- "n of m ready" counts failed Videos as finished with (`completed_videos` = done + failed) while "n videos" elsewhere means ready to answer; different word if it confuses.
- Only Sync now and Sync all are guarded in the UI. Retry failed videos, a per-Video retry, `mentor sync`, and the timer still queue a second Sync behind a running one; the UI now shows the running one first, so the queued duplicate is harmless but visible on the Syncs list.
- The header badge is Paused-only; no Active badge when `indexed`. The MCP `list_channels` description still says "indexed Channel" (API vocabulary, left alone).
