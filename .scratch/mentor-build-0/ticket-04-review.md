# Ticket 04 branch review — 2026-09-19

Fixed point: `2abd2e0` (main after Drew's Mac-test deferral and ticket 02 landing).
Independent Standards and Spec agents reviewed `git diff 2abd2e0...5971370`, the commit
list, ticket 04, spec 0003, HANDOFF conventions, CONTEXT and ADR 0002.

## Standards

Zero documented-standard violations and zero actionable smell findings. The pure path
seam takes environment/platform/home inputs. CLI checks assert observable output and refusal,
and Sync exercises the served-app harness. The parallel structure in the two required path
functions is appropriate; no extra abstraction is needed. Linux service/environment/schedule
implementation remains unchanged.

## Spec

Zero findings. The reviewed implementation covers platform defaults and override precedence,
first-start directory creation without file replacement, useful directory errors, configured
loopback URL with honest startup wording, terminal lifetime, non-Linux refusal before timer
validation/systemd work, and Sync without systemctl off Linux. README and ADR scope match.
Mac hardware verification remains deferred by Drew; no simulated test is presented as a Mac run.

## Verification

- `uv run pytest -q`: 394 passed, 4 opt-in deselected, including Playwright smoke.
- `uv run mypy`: 78 source files pass.
- `pnpm --dir web run typecheck`: pass. No web implementation changed.
- Actual isolated `.venv/bin/mentor serve`: temporary XDG roots, spare port, offline deliberately
  uncached models and CUDA hidden. Health responded; config/data directories and database were
  created; config.toml was not generated. Ctrl+C completed shutdown with exit 0.
- Live service remains active; no live data/config/model changes were made.

Standards: 0 findings. Spec: 0 findings. No deferred ticket-04 implementation findings.
