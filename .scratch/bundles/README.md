# Bundles — tickets

Status: breakdown approved by Drew on 2026-10-11. Spec: `docs/specs/0005-bundles.md` (critiqued by `reviewer` and revised). Decision: ADR 0007, written in ticket 06. Glossary: `CONTEXT.md` (Bundle).

| # | Ticket | Blocked by | Status |
|---|---|---|---|
| 01 | Share a Channel with someone who doesn't have it | — | done |
| 02 | Refuse a damaged or hostile Bundle | 01 | done |
| 03 | Import a Channel Bundle into a Library that already has some of it | 01 | done |
| 04 | Share a Playlist | 03 | ready-for-agent |
| 05 | Import beside a running server | 01 | ready-for-agent |
| 06 | Document Bundles | 02, 03, 04, 05 | ready-for-agent |

No ticket adds a migration. Tickets 02, 03, and 05 are all unblocked once 01 lands, but each changes the same import, so land them one at a time in number order.

Decisions made after the spec's critique, both in the spec: a Channel's Playlist filter does not travel in a Bundle, and unsigned Bundles are accepted for now.
