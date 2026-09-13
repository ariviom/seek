# 0002 — Single SQLite file with sqlite-vec and FTS5

Status: accepted, 2026-09-13

## Context
Several local Supabase/Postgres stacks with pgvector already run on this machine. LanceDB and other embedded vector stores were also options. Expected volume is thousands of Videos and low millions of Segments.

## Decision
All state, including vectors and the full-text index, lives in one SQLite database file in the XDG data directory, using sqlite-vec and FTS5, WAL mode.

## Consequences
- Zero infrastructure; backup is a file copy; the knowledge base is portable.
- Hybrid search is two queries against one file with no network hop.
- Single-writer semantics fit the one-Sync-at-a-time design; concurrent writers would be a reason to revisit.
- Very large corpora or ANN index needs beyond sqlite-vec's brute-force scan would push toward LanceDB or pgvector; the store sits behind a repository interface to keep that swap contained.
