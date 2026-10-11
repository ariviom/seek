# 05: Import beside a running server

**What to build:** I can import a Bundle without stopping the server. Import and a Sync never write the same Videos at once: import refuses while a Sync is running, and a Sync I queue during an import waits and then runs. If the import is interrupted, running it again carries on where it stopped. While it works, it shows progress. See Spec 0005 §Import ("The lease", "Resuming", "Progress").

**Blocked by:** 01 (Share a Channel with someone who doesn't have it).

**Status:** ready-for-agent

- [ ] Import takes the Sync lease before its first write and releases it when it ends, however it ends.
- [ ] While a Sync holds the lease, import refuses with a sentence saying to run it again when the Sync has finished, and writes nothing.
- [ ] Import renews the lease from a background thread at the worker's cadence, a quarter of the lease's length. If a renewal fails, import stops before its next Video and says to run it again.
- [ ] A Sync queued on the server during an import waits, then runs once the import releases the lease.
- [ ] The import function takes a callback it calls after each Video is committed. The CLI prints progress with it.
- [ ] An import stopped partway and run again ends with every Video searchable exactly once. Import keeps no progress record; Videos already `done` are skipped.
- [ ] With the server running, a search on the server finds an imported Segment without a restart.
- [ ] Tests hold an import open and stop one partway through its progress callback, hold a Sync open with a `Gate` for the refusal, and give the app a short Sync poll interval, since the worker finds a released lease by polling.
