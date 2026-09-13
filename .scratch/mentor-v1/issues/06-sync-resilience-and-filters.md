# 06 — Sync resilience and filters

**What to build:** An interrupted Sync picks up where it stopped when rerun. "Retry failed" per Channel recovers failures in one click. Rerunning a Sync processes only new Videos. Per-Channel filters (published after/before, playlist, most recent N) scope a large Channel. (Stories 11, 14, 15, 16.)

**Blocked by:** 05 — Sync: segmentation and embedding

**Status:** ready-for-agent

- [ ] Interrupting a Sync by raising from a fake mid-run, then rerunning, completes only the unfinished Videos (asserted via fake call counts)
- [ ] A normal Sync skips permanently failed Videos and retries transient failures; "retry failed" resets all failed Videos to their `failure_stage`
- [ ] A rerun Sync does no transcript or embed work for Videos already `done`
- [ ] Filters are editable per Channel via API and UI; every Sync re-applies the current filters, so widening a filter makes older Videos eligible and narrowing one marks them `excluded`
- [ ] API tests cover each story
