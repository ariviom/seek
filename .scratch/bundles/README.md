# Bundles — tickets

Status: breakdown approved by Drew on 2026-10-11. Spec: `docs/specs/0005-bundles.md` (critiqued by `reviewer` and revised). Decision: ADR 0007, written in ticket 06. Glossary: `CONTEXT.md` (Bundle).

| # | Ticket | Blocked by | Status |
|---|---|---|---|
| 01 | Share a Channel with someone who doesn't have it | — | done |
| 02 | Refuse a damaged or hostile Bundle | 01 | done |
| 03 | Import a Channel Bundle into a Library that already has some of it | 01 | done |
| 04 | Share a Playlist | 03 | done |
| 05 | Import beside a running server | 01 | done |
| 06 | Document Bundles | 02, 03, 04, 05 | done |

No ticket adds a migration. Tickets 02, 03, and 05 are all unblocked once 01 lands, but each changes the same import, so land them one at a time in number order.

Decisions made after the spec's critique, both in the spec: a Channel's Playlist filter does not travel in a Bundle, and unsigned Bundles are accepted for now.

**2026-10-11.** All six tickets are done on `t3code/export-shareable-channel-embeddings`. The whole-branch review found import misreporting a renewal that only timed out as another process taking the lease, a traceback from the per-Video renewal and from Ctrl+C, a Bundle with no Videos creating an empty entry, an avatar held to its host alone, and NUL passing in what was said. All are fixed in one commit; [the review record](review.md) lists them, the judgement calls left, and two sentences of the spec the code no longer matches.
