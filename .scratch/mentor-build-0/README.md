# Build 0 — approved tickets

Status: breakdown approved by Drew on 2026-09-18; ten tickets published locally and independently reviewed.
All four review findings are addressed. No implementation has started.

Source: spec 0003 (ready-for-agent), ADRs 0004 and 0005. The spec takes precedence over the desktop roadmap.
The source documents were committed as `0db90a4` before drafting this breakdown.

The approved tickets are in `issues/`, one file per ticket with `ready-for-agent` status.
The shared prerequisites below still apply before implementation starts.

| Ticket | Delivers | Blocked by |
| --- | --- | --- |
| [01 — Retrieval baseline](issues/01-retrieval-baseline.md) | Frozen real-data fixture and recorded CUDA results before any device change | None |
| [02 — Inference devices](issues/02-inference-devices.md) | CUDA, MPS and CPU models; isolated reranker fallback; usable search | 01 |
| [03 — MPS retrieval comparison](issues/03-mps-retrieval-comparison.md) | Evidence that the same questions and snapshot still retrieve the required Videos | 02 |
| [04 — Platform paths and foreground lifecycle](issues/04-platform-paths-and-lifecycle.md) | Conventional directories and a clear terminal startup on Mac | None |
| [05 — Secrets and preferences](issues/05-secrets-and-preferences.md) | Validated key storage and persistent preferences through the API | 04 |
| [06 — Selectable chat engines](issues/06-selectable-chat-engines.md) | API chat, engine selection, history, usage, and an atomic health/client migration | 05 |
| [07 — Chat settings UI](issues/07-chat-settings-ui.md) | In-app setup, live availability, model choice and token counts | 02, 06 |
| [08 — Diagnostics and MCP configuration](issues/08-diagnostics-and-mcp-config.md) | Pasteable support output and usable local agent registration | 02, 06 |
| [09 — First Channel and honest Sync progress](issues/09-first-channel-and-sync-progress.md) | Start-small guidance, explicit rate and ETA, verified restart/failure behaviour | None |
| [10 — Friends installation and release verification](issues/10-friends-installation.md) | Documented public-repository install and upgrade, verified on a Mac | 03, 07, 08, 09 |

## Before implementation

- Older-ticket prerequisite resolved on 2026-09-18: v2 ticket 06 and **v1** ticket 18 (Cloudflare Access) are explicitly
  parked, not completed. Their tickets and the handoff record the reasons and reopening criteria. Friend-workflow
  blockers remain owned by the relevant build-0 acceptance criteria; parking broad polish is not a waiver for them.
- Use the reviewed spec and ticket set on `main` as the base for implementation worktrees.
- Run ticket 01 first. The dependency graph shows actual technical prerequisites, not permission to change inference
  before recording the baseline. The numbered order is the recommended serial execution order.
- Mac access is a closure precondition for 02, 03 and 10; Drew has it. Fake probes do not satisfy these checks.
- Follow the handoff's implementation process: one ticket per session in a worktree off `main`, with `opus-worker`
  subagents and a reviewer pass over the whole branch at the end. Every ticket lands with `main` working.
- Ticket 06 is deliberately the largest slice: the spec requires the new engine, selection and status to land
  together, and the health rename must include the CLI, web clients, tests and rebuilt bundle. Do not split those
  contracts across merges. Ticket 05 makes the change easier by supplying validated secrets and preferences first.
- Ticket 03 owns the same-snapshot regression evidence; ticket 02 owns actual Mac execution and fallback behaviour.
  A failure in 03 is fixed there, not deferred to release or hidden by changing expected Videos.
- The packaging spike is optional, separately chosen, and blocks no ticket. No installer work is included here.

## Coverage and verification

| Spec stories | Owning tickets |
| --- | --- |
| 1–2, 8, 33, 40, 47 | 10 |
| 3–5 | 04 |
| 6–7 | 02, with fresh-install verification in 10 |
| 9–13 | 02 |
| 14 | 01, 03 |
| 15–16 | 06, 07 |
| 17–18 | 05, 07 |
| 19–26 | 06, 07 |
| 27–30 | 05, 06, 07 |
| 31–32, 34–35 | 09, with real Mac verification in 10 |
| 36–39, 46 | 08 |
| 41–45 | 06, 07 |

Each ticket names its behaviour-level checks. Normal implementation checks remain pytest, mypy, and web typecheck;
web changes rebuild the served bundle and keep the Playwright smoke test green. Real-model tests are opt-in. No
implementation checks or hardware runs have been claimed by this documentation-only planning session.

The ticket set was checked against the current ports, chat orchestration, model wrappers, search, CLI, build hook,
health consumers, Sync progress and prior ticket conventions. Independent review and focused correction review are
complete; [the review record](review.md) documents all four findings, their resolution and the older-ticket decisions.

Drew approved the proposed granularity and blocking edges on 2026-09-18, satisfying the `to-tickets` approval
checkpoint. Ticket 06 retains its approved atomic scope.
