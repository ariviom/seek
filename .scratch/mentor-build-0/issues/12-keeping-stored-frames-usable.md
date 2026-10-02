# 12 — Keep stored frames usable as their links age

**What to build:** Frames stored by ticket 11 keep working after their signed links stop resolving, without a page
view ever becoming a burst of YouTube calls.

**Blocked by:** 11 — Show frames of the cited moment. Also blocked on a measured fact, below.

**Status:** blocked — needs the lifetime measurement before it can be designed honestly

**The measurement:** storyboard fragment URLs are signed and cannot be rebuilt from a Video id; the geometry is
stable, so only the links go stale. How long they last is being measured at
`~/.local/share/mentor-storyboard-ttl/ttl.log` (a probe re-fetching one captured URL every 15 minutes until it
fails). One URL was still resolving 2h21m after extraction. Do not design this ticket until the log shows a failure
or the probe reaches its 72-hour limit, because the answer decides the shape:

- **Days** — refresh on a slow background schedule; stored links are usually good, and the work is small.
- **Hours** — a stored link is almost always stale, so either refresh lazily under a strict budget, or accept that
  frames show only for recently fetched Videos. A per-view extraction is not acceptable at any volume.

**Constraints any design must respect (from review of ticket 11):**

- `youtube.py` has two modes today: a Sync-paced one serialising on a shared delay with throttle backoff, and an
  unpaced one with no retry. Neither fits refreshing on demand. A third mode, with its own cap, is likely required.
- A chat citing a dozen Videos, or a cold search page of twenty, must not become a dozen or twenty extractions. The
  worker's throttle counter can stop a running Sync outright, so UI activity must never be able to halt ingestion.
- This project has already tripped YouTube bot detection once; a stale strip is always better than a blocked account.
- An expired link rendered as a CSS background is an undetectable blank tile. Whatever ticket 11 chose for detecting
  a failed fragment is what this ticket must build on.

**Verification:** Record the measured lifetime here before writing criteria. Then: tests that a view never triggers
an extraction beyond the agreed budget, that concurrent requests for one Video share a single refresh, that a
rate-limited refresh degrades to no frames, and that a running Sync's timing is unaffected.
