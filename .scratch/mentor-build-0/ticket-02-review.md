# Ticket 02 branch review — 2026-09-19

Subsequent execution decision: Drew explicitly deferred Mac testing because no Apple Silicon machine is available
(2026-09-19). The reviewed implementation is accepted for landing; the Mac check remains unchecked and unverified.
The original review's hardware closure blocker below is superseded by that decision, not satisfied by Linux tests.

Fixed point: `61334e9`. Separate Standards and Spec reviewers inspected
`git diff 61334e9...b7b39ad`, the ticket, spec, ADR and surrounding implementation.
A Standards attempt hit a usage limit; the retry completed. Available agents were used;
the unavailable opus-worker model is not claimed.

## Standards

No documented-standard violations. One low-priority possible duplication smell in the
external Encoder fake used for runtime failure tests at the model-port and HTTP seams.
Disposition: retain the small explicit setups so each test independently explains its
warm-up/first-call/CPU-retry sequence. There is no production duplication or correctness
finding to fix. Both test seams are requested by the ticket.

## Spec

No implementation findings. The reviewer confirmed device/precision selection, both CLI
entry paths, warm-up/runtime fallback and one-time retry, serialized model use, CPU failure
status, CUDA-only cleanup, preserved embedding OOM recovery, fused HTTP/MCP results,
continuing events and additive status fields, offline cache and download progress.

Actual Apple Silicon execution remains outstanding and is a closure blocker. Passing Linux
CPU execution and the CUDA corpus regression do not substitute for it. The branch and ticket
remain in-progress and are not landed on main.

## Evidence

`docs/inference-devices.md` links actual clean-revision CUDA and CPU reports and contains exact
Mac verification commands. Linux tests: 366 passed, 4 opt-in deselected. Mypy, web typecheck,
bundle build and existing Playwright smoke passed. Focused status UI verification included
desktop, mobile and 200% zoom; model details were changed to wrap after the first inspection
found them truncated. Final confirmation passed.

Standards: zero hard violations, one optional test-setup smell retained with rationale.
Spec: zero implementation findings; one outstanding required hardware verification.
