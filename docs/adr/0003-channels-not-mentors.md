# 0003 — A Channel is the unit; "Mentor" is only the product's name

Status: accepted, 2026-09-14

## Context
v1 modelled a Mentor (a creator) that owns one or more Channels, and Groups as sets of Mentors. Using the tool, every
action is on a channel or a group of channels: paste a channel URL, watch it sync, ask a group. The Mentor layer added a
second name for the same thing, an extra step (create the Mentor, then attach its channel), and a "creator with two
channels" case nobody has. The UI prototype (branch `t3code/sidebar-chat-ui-prototype`, commit `8d51635`) was judged
clearer with Channels and Groups alone. The one installed knowledge base holds no Mentors, so reshaping the schema
costs nothing today.

## Decision
A **Channel** (a YouTube channel) is the unit of ingestion, search scope, and citation. A **Group** is a named set of
Channels. A **Conversation** is scoped to exactly one Group or one Channel; a Channel alone works like a group of one,
without creating a Group. The word "Mentor" names the product and nothing else: not a table, a route, a tool
parameter, a field, or a label.

## Consequences
- Schema 9 rebuilds the affected tables the way SQLite documents (foreign keys off around the rebuild, new tables
  renamed into place, `foreign_key_check` before commit), carrying Channels, Groups, and Conversations across: a
  Mentor's channels each join its Groups. Migration entries may now be Python callables for this.
- Renames across the API (`/channels` replaces `/mentors`; group members are channel ids), the MCP tools (`channels`
  replaces `mentors` in `search`; `list_channels` joins `list_groups`), search results and citations (no
  `mentor_name`), the chat prompts, the CLI, the glossary, the README, and the tests.
- A creator with two channels is represented by a Group named after them.
- Reversal means reintroducing a creator entity above Channels; retrieval and ingestion code would not change.
