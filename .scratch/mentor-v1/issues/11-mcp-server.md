# 11 — MCP server

**What to build:** MCP clients connect to mentor over Streamable HTTP and get `list_groups`, `search`, `expand`, `get_video`, and a read-only `sql`, with instructions that make the model a grounded advisor. The web UI can also expand a search result to show surrounding transcript. (Stories 28–30, 34.)

**Blocked by:** 09 — Hybrid search

**Status:** ready-for-agent

- [ ] Streamable HTTP MCP endpoint hosted by `mentor serve`; tool functions are shared with the HTTP API
- [ ] Server instructions and every tool description embed the grounded-advisor guidance
- [ ] `search` returns the same shape as the API; `expand` returns contiguous cue-timed text around a Segment; `get_video` returns title, Mentor, Channel, date, duration, chapters, description, URL
- [ ] `sql`: read-only connection with query-only mode, extension loading disabled after sqlite-vec loads, an authorizer allowing only reads, a time limit enforced by a progress handler, and a row cap; writes, `load_extension`, and multiple statements are rejected
- [ ] MCP transport's allowed-hosts list is configurable so proxied Host headers are not rejected by DNS-rebinding protection
- [ ] Expand available in the API and the search UI
- [ ] Tests over an in-memory MCP client: tool listing, guidance present, search shape parity, sql rejections including `load_extension`

From ticket 09 review:
- Reuse `search.Search` (built in `create_app`) for the `search` tool. State the Group rule in its description: a number is a Group id, a string is a Group name. `limit` is 1–50; `prefer_recent` is `off | gentle | strong`.
- The web Search section (`web/src/Search.tsx`) is where Expand goes; results carry `segment_id`.
