# 0006 — A Playlist is its own scope over Videos; Videos stay credited to their Channels

Status: accepted, 2026-10-10

## Context
The MVP plan (`docs/product/desktop-mvp.md` §3) treated a playlist as a Channel-like source, "a Channel of one
publisher". A curated playlist mixes creators, so that would credit every cited moment to the playlist rather than the
person speaking, fill the Library with a pseudo-Channel, and clash with a Video already belonging to a Channel you
follow (`videos.youtube_video_id` is unique).

## Decision
A **Playlist** is a third kind of Library entry and scope, beside Channel and Group: a set of Videos imported from a
YouTube playlist URL (private ones through Seek's existing YouTube cookies) and kept in step with it. Every Video stays credited to its real Channel. A
creator you have not added gets a Channel outside the Library, which is never synced on its own or offered as a scope;
adding that creator later brings the same Channel into the Library and reuses its indexed Videos. Groups stay
Channel-only.

## Considered Options
- **Playlist as a Channel** (the MVP plan): no new scope kind, but wrong attribution and duplicate-Video conflicts.
- **Videos without a Channel**, holding only the creator's name: no hidden Channels, but every Channel-shaped path
  (citations, avatars, chat fallback, scope) would need a special case.

## Consequences
- Scope resolution grows a Video-set kind alongside Channel sets: search, `expand`/`get_video`, saved Citations,
  Conversation scope, and the bound MCP server all honour it.
- Exclusion is per Video, not per scope: a Video any Playlist includes is searchable even where its Channel's filters
  would exclude it (the minimum length still applies). A Video is deleted once no Library Channel or Playlist includes it.
- Pausing is per Library entry: a Video is searchable in "everything" while any Active Library Channel or Active
  Playlist includes it.
- Single-video sources from MVP §3 are not covered by this decision.
