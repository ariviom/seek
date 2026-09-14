# 11 — MCP server

**What to build:** MCP clients connect to mentor over Streamable HTTP and get `list_groups`, `search`, `expand`, `get_video`, and a read-only `sql`, with instructions that make the model a grounded advisor. The web UI can also expand a search result to show surrounding transcript. (Stories 28–30, 34.)

**Blocked by:** 09 — Hybrid search

**Status:** done

- [x] Streamable HTTP MCP endpoint hosted by `mentor serve`; tool functions are shared with the HTTP API
- [x] Server instructions and every tool description embed the grounded-advisor guidance
- [x] `search` returns the same shape as the API; `expand` returns contiguous cue-timed text around a Segment; `get_video` returns title, Mentor, Channel, date, duration, chapters, description, URL
- [x] `sql`: read-only connection with query-only mode, extension loading disabled after sqlite-vec loads, an authorizer allowing only reads, a time limit enforced by a progress handler, and a row cap; writes, `load_extension`, and multiple statements are rejected
- [x] MCP transport's allowed-hosts list is configurable so proxied Host headers are not rejected by DNS-rebinding protection
- [x] Expand available in the API and the search UI
- [x] Tests over an in-memory MCP client: tool listing, guidance present, search shape parity, sql rejections including `load_extension`

From ticket 09 review:
- Reuse `search.Search` (built in `create_app`) for the `search` tool. State the Group rule in its description: a number is a Group id, a string is a Group name. `limit` is 1–50; `prefer_recent` is `off | gentle | strong`.
- The web Search section (`web/src/Search.tsx`) is where Expand goes; results carry `segment_id`.

Deferred at ticket 11 review (judgement calls, no owning ticket):
- `sql` tests exercise only the authorizer: every rejection is denied before running, so removing `mode=ro`, `query_only`, or disabling extension loading would stay green.
- `sql`'s "a SELECT ran" check also counts SELECTs FTS5 runs internally, so `PRAGMA table_info(segments_fts)` is accepted while `PRAGMA table_info(videos)` is refused. Both are reads.
- Duplication to fold when next touched: `groups.group_summaries` repeats `_select_groups`; `sources.get_video` repeats `videos._video`'s row parsing (and shares a name with `videos.get_video`); `sql.run_query` repeats `db.connect`'s sqlite-vec loading; `mcp_server._tool_errors` keeps a second list of user-facing errors beside `app.ERROR_STATUS`; expanded lines normalise cue text as `segmentation._window` does.
