# 11 — Show frames of the cited moment

**What to build:** A friend scanning search results or an answer's sources can see what was on screen around the
moment a Segment cites, and can turn those frames off.

**Blocked by:** None. Keeping stored frames usable as their links age is ticket 12, deliberately split out.

**Prototype:** branch `t3code/prototype-thumbnails` — variant C won; a, b, d, e record what lost. Throwaway code,
not the design. Rewrite rather than promote it.

**Status:** complete — 572 tests passing (browser smoke included), mypy 98 files and web typecheck clean, served
bundle rebuilt. One signature does cover every sheet of a Video (all 25 captured Videos, plus a live check through
the adapter), so a URL template and a sheet count are stored rather than a list of URLs; a Video whose sheets
disagreed would be treated as having no storyboard rather than stored under a template that 403s. Signed URLs leave
the server only from `POST /api/frames`; the search payload and the MCP tools' output are unchanged.

The backfill runs in its own process with its own pacing and its own copy of the cookie jar, so it never waits on a
Sync, never makes one wait, and never rewrites the jar yt-dlp rotates under a running Sync. What it cannot be is
invisible to YouTube: both processes reach it from one address, so running them together raises the rate YouTube
sees and a refusal brought on by the two can land on the Sync's throttle counter and stop it. The command warns
when a Sync is queued or running, and the honest advice is to run it when none is.

Three further limits, recorded rather than hidden: a Video whose extraction offers no storyboard keeps no row, so a
later backfill run asks about it again (none of 25 measured Videos lacked one, though a 19-second Video genuinely
does); "no measurable time" in ingestion is argued rather than benchmarked — the geometry is parsed from the
extraction dict already in memory and the tests assert one `fetch_video` per Video, as before; and the last tile is
worked out from a rounded duration divided into a derived fps, so the conservative end of that rounding is taken,
which can cost the single final frame of a Video rather than risk painting an empty cell of a sheet that loaded.

- [x] Store one `storyboards` row per Video, as `transcripts` is stored: tile width/height, rows, columns, frames per
  second, fragment count, the URL template every fragment shares, and when it was fetched. No row is the honest
  state for a Video never fetched, and the table keeps refresh writes off the `videos` row the Sync worker updates.
  Confirm one signature really does cover every fragment before storing a template rather than a list.
- [x] Capture that geometry from the extraction ingestion already performs. Verify it adds no YouTube call and no
  measurable time, and that a Video whose storyboards are absent or malformed still ingests, syncs and searches
  exactly as before.
- [x] Add a paced, resumable `mentor backfill-storyboards` for the ~1840 Videos already ingested, scoped to a
  Channel or all, through the same pacing a Sync uses. Nothing else in this ticket may call YouTube: no refresh on
  view, no fetch triggered by search, chat or page load. Running it while a Sync runs must not delay the Sync.
- [x] Serve fragment URLs from a dedicated endpoint, never as fields on `SearchResult` or `Citation`, so signed URLs
  stay out of MCP tool output and the search payload is unchanged. Confirm MCP output is byte-identical to today.
- [x] Each strip samples frames forward from the cited moment at the Video's own storyboard interval: five in search,
  three in the Sources column. Derive the span from stored geometry alone — no new field on search or citation
  payloads. Handle the first frame, the last fragment, and a span running past the end of the Video.
- [x] Render as variant C: in search, a run of consecutive results from one Video carries a title line and one
  compact strip, and those rows drop the repeated title; grouping is of consecutive results only and must not
  reorder or regroup what ranking returned. In Sources, each Channel group carries a per-Video strip and its rows
  lead with the moment's time. Hover or keyboard focus opens that frame at one fixed 320px width for every tier.
- [x] A `Thumbnails` control in the Sources panel header sets a single stored preference governing both surfaces, in
  the settings table as ticket 05 established, reachable from settings too since it governs the search view as well.
  With frames off, rows restore the titles the strips were carrying. Both states survive a reload.
- [x] A Video with no stored geometry, or a fragment that fails to load, shows no frames: never a broken image, a
  spinner that never resolves, a blank tile, or a retry. Detect a failed fragment rather than assuming success —
  roughly a quarter of Videos offer only a 160x90 tier (18 of 25 measured at 320x180, 7 at 160x90), and those
  upscale soft in the preview. Accept the softness rather than varying the preview's size, and claim no legibility.
- [x] Frames are an index, not evidence. This ticket sends no image to any model, adds no ffmpeg, downloads no media
  and stores no image file. Reading on-screen detail belongs to its own ticket.

**Verification:** Tests for geometry capture from a recorded extraction, timestamp-to-tile arithmetic at the
boundaries above, the backfill's pacing and resumption, the endpoint, and the preference in both states. No test may
reach YouTube; use the existing fake source. A migration test against a database holding the current schema, an
unchanged-MCP-output test, and a browser smoke test for a strip, the preview by hover and by keyboard, and the
toggle across a reload. Full suite, mypy and web typecheck clean; rebuild the served bundle.
