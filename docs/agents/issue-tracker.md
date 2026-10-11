# Issue tracker: Local Markdown

Specs and tickets for this repo live as markdown files in the repo. There is no remote tracker; the GitHub remote has no issues.

## Conventions

- Specs: `docs/specs/NNNN-<slug>.md`, numbered after the highest existing spec, with a `Status:` line under the title.
- One feature per directory: `.scratch/<feature-slug>/`.
- Tickets: one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`, never a single combined tickets file. Each carries a `Status:` line (see `triage-labels.md` for the role strings) and a `**Blocked by:**` line near the top.
- `.scratch/<feature-slug>/README.md` indexes the tickets and records approvals and progress. Ticket reviews sit beside it as `ticket-NN-review.md`.
- Comments and conversation history append to the bottom of a ticket under a `## Comments` heading.

## When a skill says "publish to the issue tracker"

A spec is written to `docs/specs/`. Tickets are written under `.scratch/<feature-slug>/issues/`, creating the directory and its `README.md` if needed.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the ticket number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` (the Notes / Decisions-so-far / Fog body).
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
