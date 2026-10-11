# 05: Import beside a running server

**What to build:** I can import a Bundle without stopping the server. Import and a Sync never write the same Videos at once: import refuses while a Sync is running, and a Sync I queue during an import waits and then runs. If the import is interrupted, running it again carries on where it stopped. While it works, it shows progress. See Spec 0005 §Import ("The lease", "Resuming", "Progress").

**Blocked by:** 01 (Share a Channel with someone who doesn't have it).

**Status:** done

- [x] Import takes the Sync lease before its first write and releases it when it ends, however it ends.
- [x] While a Sync holds the lease, import refuses with a sentence saying to run it again when the Sync has finished, and writes nothing.
- [x] Import renews the lease from a background thread at the worker's cadence, a quarter of the lease's length. If a renewal fails, import stops before its next Video and says to run it again.
- [x] A Sync queued on the server during an import waits, then runs once the import releases the lease.
- [x] The import function takes a callback it calls after each Video is committed. The CLI prints progress with it.
- [x] An import stopped partway and run again ends with every Video searchable exactly once. Import keeps no progress record; Videos already `done` are skipped.
- [x] With the server running, a search on the server finds an imported Segment without a restart.
- [x] Tests hold an import open and stop one partway through its progress callback, hold a Sync open with a `Gate` for the refusal, and give the app a short Sync poll interval, since the worker finds a released lease by polling.

## Comments

**2026-10-11, implemented.** `import_bundle(config, path, name=None, progress=None)` holds the Sync lease while it writes. `_sync_lease` in `bundles.py` takes it with `syncs.acquire_lease`, renews it with `syncs.renew_lease`, and gives it up with `syncs.release_lease`, all at `sync_worker.LEASE_SECONDS`: the worker's own functions and length, nothing copied. `seek import` prints progress. Tickets 02 to 04 are untouched: the whole Bundle is still checked before the knowledge base is opened, and the merge and its write guards are as they were. Tests: four in `tests/test_bundles.py` (stopped partway and run again; refused while a Sync runs; the lease lost; beside a running server) and one assertion in the CLI round trip.

Readings taken:
- **Where the lease is taken.** After the whole Bundle is validated and the knowledge base opened, before the entry step, which is the first write; as tickets 02, 03, and 04 said. A Bundle refused as damaged never touches the lease. Opening the knowledge base still comes first, since the lease lives in it, so an import into a data directory never started creates and migrates it before taking the lease.
- **The refusal** is `A Sync is running; run the import again when it has finished`, a `SyncCommandError`, so the CLI prints it after `seek:` and exits non-zero. It is given whenever another holder's lease is unexpired, which includes the up to 20 seconds after a server was killed mid-Sync.
- **Taking the lease does what a worker taking it does**: `acquire_lease` requeues any Sync a stopped worker left `running`. Nothing new, but an import is now one more thing that does it.
- **Renewal is in two places.** A background thread, on a connection of its own, renews every quarter of the lease, as the ticket asks; it covers a Video, or a progress callback, that takes longer than the lease lasts. Import also renews on its own connection before each Video and takes a failure there as the lease lost. That second renewal is my addition: with the thread alone, an import would go on writing Videos for up to five seconds after another process took the lease, and no test could see the stop without waiting that long. It costs one small write per Video.
- **A lease lost** stops the import before its next Video with `Another seek process took over running Syncs after N of M Videos; run the import again to carry on where it stopped`. What was committed stays. The release that follows deletes only this import's own lease, so the other process keeps the one it took.
- **Released however it ends**: a refusal in the entry step, an exception from the callback, Ctrl+C. A release that itself fails with a SQLite error is swallowed, as the worker logs and swallows its own, so it can't replace whatever ended the import; the lease then expires on its own.
- **The callback is `progress(videos, total)`**, called after each of the Bundle's Videos, once its transaction has committed, whether it was filled in, already indexed, or left out (ticket 03's open question): `videos` is how many are behind the import, `total` how many the Bundle holds. An exception it raises ends the import with everything so far committed.
- **The CLI prints `Importing: N of M Videos` on stderr**, each ending in a carriage return so the next count, the report, or a refusal is written over it. Stdout carries only the report, as before. It prints counts and nothing from the Bundle.
- **Resuming needed no code**: ticket 03's merge already skips `done` Videos. The test pins it, and that the stopped import released the lease, since the second run would otherwise be refused.
- **The test of the queued Sync shortens the lease** to two seconds by setting `sync_worker.LEASE_SECONDS`, which `bundles.py` reads at call time for that reason. It holds the import open in its callback until the lease as first read has run out, then finds the Sync still queued: only the background renewal explains that. It waits on that condition, not for a fixed time, and the thread has a second and a half of slack before a late renewal would lose the lease. `app_on` in the tests gained `sync_poll_seconds`.
- **The lost-lease test writes `sync_lease` directly**, as `test_a_sync_waits_while_another_process_holds_the_lease` does: no surface takes a lease away.

Changed assertions: none. One added to `test_export_and_import_carry_a_channel_between_data_directories…`: stderr of the first import is `Importing: 1 of 1 Videos\r`. Its `run` helper now keeps stderr as well as returning stdout.

Not done: the thread's own failure path (a renewal that fails in the background sets a flag the next check reads) has no test of its own; the per-Video renewal is what the lost-lease test exercises.

For ticket 06: see the line added to its comments.
