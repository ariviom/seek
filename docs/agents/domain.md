# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase. This repo is single-context.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root: the domain glossary. It plays the role the skills call `GLOSSARY.md`; update it, don't create a `GLOSSARY.md`.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

## Use the glossary's vocabulary

When your output names a domain concept (in a ticket title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0006 (Playlists scope Videos, not Channels), but worth reopening because…_
