# Build-0 ticket review — 2026-09-18

Independent read-only review completed by a separate reviewer agent, followed by a focused confirmation of the
corrections. All four findings were P2 and are addressed. No dependency-cycle or approved atomic-scope issue was
found. The ten-ticket breakdown and blocking edges are unchanged.

Scope: all ten tickets and their index, spec 0003, ADRs 0004/0005, the planning branch diff, relevant
chat/model/search/Sync/config/lifecycle/security implementation, packaging metadata and existing test seams.

| Finding and concrete failure | Disposition |
| --- | --- |
| Clearing the CLI session only after a completed API answer leaves CLI → failed/canceled API → CLI missing a persisted user question. | Ticket 06 now invalidates the session atomically with accepting/persisting the API turn; requires success, failure, cancellation and restart coverage. Spec clarified. |
| A paid tool-loop response followed by cancellation, failure or turn limit loses usage when persistence only happens on answer completion. | Ticket 06 retains reported usage on the initiating message, counts it once and marks incomplete measurements. Ticket 07 displays known/incomplete totals. Spec clarified. |
| Sync recovery resets `started_at` while retaining `completed_videos`, so old completed work divided by fresh elapsed time yields a false rate/ETA. | Ticket 09 requires compatible count/time baselines or a fresh warm-up interval without losing total progress, tested after nonzero completed work. Spec clarified. |
| An old key A's delayed authentication failure can invalidate newly validated replacement B. | Tickets 05/06 tie validation and failure handling to credential generations, including replacement/deletion races; a delayed-A/validated-B test is required. Spec clarified. |

The reviewer confirmed that all four corrections resolve the findings and agree across tickets 05, 06, 07, 09 and
the spec, with no new contradictions found in the focused diff. These are acceptance-criteria corrections; no
implementation or hardware verification was performed or claimed.

## Older-ticket recommendations adopted

Drew authorized recommendations and proceeding with their disposition before landing the branch.

- **v2 ticket 06: parked, not completed.** Its broad UI finish pass is deferred until after the friend check-in,
  unless a specific defect blocks the supported friend workflow. Existing prototype wiring is absent from the
  current entry point/source tree, while known narrow-screen search focus and Conversation recovery issues remain
  recorded. Build-0 tickets 07, 09 and 10 retain responsibility for their own usability and end-to-end criteria;
  this does not import every old polish item or waive a blocking defect.
- **v1 ticket 18: parked, not completed.** Remote MCP/Claude Desktop authentication is outside build 0's local
  distribution path. Resume when Drew chooses that surface, with fresh provider-documentation checks and the
  required dashboard/client-login participation. Existing Access protections/configuration were not changed,
  and historical live checks were not presented as new verification.

The owning tickets and handoff record both dispositions and reopening criteria. This resolves the spec's
finish-or-park prerequisite.

## Validation and next step

Documentation checks cover ticket statuses, acceptance criteria, forward-only dependency edges, index links,
complete story coverage and whitespace. No application code changed, so implementation test suites were not run.
After this planning branch lands on `main`, implement ticket 01's frozen CUDA retrieval baseline in a new worktree.
Each later ticket remains one implementation session; Mac verification is mandatory for 02, 03 and 10.
