# Playlists — tickets

Status: breakdown approved by Drew on 2026-10-10. Spec: `docs/specs/0004-playlists.md` (critiqued by `reviewer` and revised). Decision: ADR 0006. Glossary: `CONTEXT.md` (Library, Playlist, Playlist filter).

| # | Ticket | Blocked by | Status |
|---|---|---|---|
| 01 | Scope resolves to Videos (prefactor) | — | done |
| 02 | Channels outside the Library (prefactor) | — | done |
| 03 | Add and sync a Playlist over the API | 02 | done |
| 04 | Playlists in the Library | 03 | done |
| 05 | Search a Playlist | 01, 03 | done |
| 06 | Chat in a Playlist | 05 | done |
| 07 | Follow the playlist on YouTube | 03, 04 | done |
| 08 | Pause, rename, and check schedule | 04, 06 | done |
| 09 | Delete a Playlist; creators joining and leaving the Library | 06, 07 | done |
| 10 | Playlists in the CLI | 03 | done |

Each ticket adds its own migration, so land them one at a time in number order, even where the blocking edges would allow parallel work.

## Review fixes

**2026-10-10.** The whole-branch review found three ways to lose or strand indexed Videos: a video YouTube lists without its creator (private or deleted) counted as removed from a Playlist, and from a Channel's playlist filter (07's reading of the Sources port); and a Video excluded inline by a Playlist or Channel delete while a Sync was part-way through it ended done with no Segments (09's uncovered case).
A `PlaylistListing` now carries `video_ids`, every id listed, beside its creator-bearing `entries`: a membership stays while its id is listed, `position` is the place in the full listing, and the playlist filter goes by the ids. The stage writes after the fetch return a `StageOutcome` and stop at an excluded Video (`videos.standing`).
A second commit holds the review's smaller findings (copy, names, duplications, tests moved onto public surfaces, the Playlist table's reload).
