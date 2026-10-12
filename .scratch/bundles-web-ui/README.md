# Bundles in the web UI — tickets

Status: breakdown approved by Drew on 2026-10-11. Spec: `docs/specs/0006-bundles-web-ui.md` (critiqued by `reviewer` and revised). Builds on Spec 0005 and ADR 0007, which gains a note in ticket 06. Glossary: `CONTEXT.md` (Bundle). The grilling session's ten decisions are in [the handoff](handoff.md) and are closed.

| # | Ticket | Blocked by | Status |
|---|---|---|---|
| 01 | Export a Channel from its page | — | ready-for-agent |
| 02 | Export a Playlist from its page | 01 | ready-for-agent |
| 03 | Import a Bundle from the Add dialogs | 01 | ready-for-agent |
| 04 | Import waits for Syncs and for another import | 03 | ready-for-agent |
| 05 | Limits and leftovers | 04 | ready-for-agent |
| 06 | Document Bundles in the web UI | 02, 05 | ready-for-agent |

No ticket adds a migration or a dependency. Tickets 02 and 03 are both unblocked once 01 lands, but they share the Bundle routes and the web's API module, so land them one at a time in number order.

Every ticket is tested at the spec's two seams and no other: the HTTP API on the existing harness, with apps built on a `Config` naming the fake embedder's model, and the browser smoke tests. Spec 0005's tests pass unchanged throughout. Verify with `uv run pytest -q && uv run mypy`, and the web typecheck and build; a fresh worktree needs `pnpm --dir web install --frozen-lockfile` first.
