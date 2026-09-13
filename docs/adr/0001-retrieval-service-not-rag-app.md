# 0001 — Mentor is a retrieval service; the chatting model is external

Status: accepted, 2026-09-13

## Context
The original idea was a full RAG app with its own LLM. A capable local model (Qwen via llama-server) is available on this machine. Frontier models are also available at no marginal cost through the user's Claude subscription, via Claude Code, Claude Desktop, Codex, and the Claude Agent SDK.

## Decision
Mentor ingests, indexes, and retrieves. It never generates answers. Every consumer, including Mentor's own web chat, uses an external frontier model that calls Mentor's MCP tools. The web chat drives the local Claude CLI through the Claude Agent SDK.

## Consequences
- No prompt tuning against a weaker local model; answer quality tracks the frontier.
- The MCP tool surface is the product's primary interface, so its descriptions carry the grounded-advisor behaviour.
- The web chat depends on the Claude CLI being installed and logged in. Without it, retrieval still works through MCP clients.
- Reversal would mean adding a generation pipeline and UI-side prompt tuning; retrieval code is unaffected.
