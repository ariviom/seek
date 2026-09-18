# 0004 — Two chat engines behind one port; Anthropic API is the default

Status: accepted, 2026-09-17

## Context
Web chat drives the user's Claude Code CLI through the Claude Agent SDK. That works because the one user has Claude
Code installed and logged in, and it bills their subscription. Distributing Mentor to friends breaks both assumptions:
most will not have the CLI, and driving someone's consumer Claude subscription from a distributed application may not
be permitted by Anthropic's consumer terms — a question that gets sharper the further Mentor travels.

A friend who brings their own API key pays a few cents a day and needs nothing installed. A friend who already has
Claude Code should not be made to pay twice.

## Decision
`ChatEngine` remains the single port. Two adapters implement it: the existing Claude CLI engine, and a new `ApiEngine`
that runs its own tool loop against the Anthropic SDK. Both emit the same event stream, are handed the same scoped
in-process MCP tools and the same system prompt, and are indistinguishable to `Chat`, to the HTTP API, and to the UI.

The API engine is the default where a key exists. The Claude CLI engine is a power-user path, offered to those who
already have it. Anthropic is the only provider; other providers wait for someone to ask.

Chat is the only thing a key gates. Search, the Library, Syncs, and the MCP tools work without one.

## Consequences
- Tool schemas are translated from the MCP server's own listing per provider format, never hand-written, so the two
  engines cannot drift apart.
- The API path keeps no provider-side session: history is replayed from our store every turn, and the session id an
  engine reports becomes optional. The session-lost retry stays meaningful only for the CLI path.
- Secrets need a home. The OS keychain is it, behind a `Secrets` port, with an owner-only file in the data directory as
  the fallback wherever the keychain is missing, locked, or refused. Deliberately not an environment variable: the
  systemd unit unsets `ANTHROPIC_API_KEY`, and the Claude CLI treats its presence as a reason to bill the key rather
  than the subscription, so an environment fallback could charge a friend without telling them.
- This amends ADR 0001, which records that web chat depends on the user's Claude CLI. It now depends on a chat engine,
  of which the CLI is one.
- Read-only project and web context stays a Claude CLI capability: those tools are CLI built-ins rather than MCP tools.
  Engine parity holds for Mentor's own tools, not for the CLI's extras.
- Engine, model, and token counts are recorded per message, so cost and provenance are answerable later.
- Health and status gain per-engine states, including "no key" and "invalid key"; the health field named for the Claude
  CLI is renamed for the active engine.
- The subscription-terms risk is contained: the CLI path only ever runs against a CLI the user installed and logged
  into themselves. If it has to be withdrawn, the API path is already the default and nothing else moves.
