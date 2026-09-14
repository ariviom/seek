# 12 — Web chat

**What to build:** Open a Mentor Group in the web UI, ask a question, and watch a grounded answer stream in with tool calls visible. It runs on the local Claude CLI through the Claude Agent SDK and can use mentor tools only. (Stories 36–40.)

**Blocked by:** 11 — MCP server

**Status:** done

- [x] Claude Agent SDK ChatEngine adapter streams text deltas, tool calls, tool results, done, and error events
- [x] Lockdown: `allowed_tools` alone is not enough. Built-in tools are disabled, only the in-process mentor MCP server is configured (strict), no user settings, skills, plugins, or hooks load, and it runs in a fixed empty working directory. Verify the option names against the installed SDK version
- [x] In-process tools are bound server-side to the Conversation's Group; the model cannot widen scope
- [x] Grounded-advisor system prompt per spec
- [x] Conversation create (Group, model) and `POST message` returning an SSE stream; the user message persists before streaming; one turn per Conversation at a time
- [x] Assistant messages persist on completion with durable citation data (Video id, seconds, Mentor and Video names); the Claude session id is stored
- [x] UI chat view renders streaming text and tool calls
- [x] API tests with FakeChatEngine assert every lockdown option and the Group binding it received, plus persistence

From ticket 01 review: ChatRequest has no fields for the tool lockdown, Group binding, or replay history, and ChatFailed cannot signal an unresumable session; reshape the port here.

From ticket 11 review:
- `mcp_server.create_mcp_server(database, search, sql_time_limit_seconds)` has no Group binding and its tools are closures; reshape it so the in-process server reuses the tool bodies with a bound Group. `expand`, `get_video`, and `sql` read across every Group, so either scope them or leave `sql` out of the chat.
- `mcp_server.GROUNDED_ADVISOR` is the grounded-advisor text already worded from the spec's chat system prompt; build the system prompt from it so the two don't drift.
- `list_groups` only lists Mentors that belong to a Group, so a Mentor in no Group has no id the model can find except through `sql`.
- `sql` runs on the default thread pool shared with `Database.run`; stateless MCP has no concurrency limit, so many slow `sql` calls at once can stall the API and the Sync worker. Consider a small dedicated executor.
- Building `MCPServer` calls `logging.basicConfig` (at WARNING, with a Rich handler when `rich` is installed), which changes how existing `log.exception` output looks.

Decisions at implementation (2026-09-13):
- The lockdown options are asserted on `claude_chat.chat_options` (the adapter's pure option builder), not through a FakeChatEngine: they are adapter details a fake can't see. API tests with the fake assert the Group binding, tool names, system prompt, and persistence. A manual run against Claude Code 2.1.270 confirmed no Bash/Read, Group-bound search, and saved Citations. The CLI still lists ListMcpResourcesTool/ReadMcpResourceTool/ReadMcpResourceDirTool to the model even when disallowed, but calls to them are denied.
- `sql` is left out of the chat, since it reads every Group's data; counting questions go unanswered there.
- Citations are resolved when the answer is saved: YouTube watch links in the answer (any common form) that point at searchable Videos of the Group's Mentors, so a Video found in an earlier turn is still cited.

Deferred at ticket 12 review:
- Every turn repeats the grounded-advisor text in the system prompt, the server instructions, and all four tool descriptions.
- `ports.ChatRequest.tools` is mcp's concrete `MCPServer`, and the adapter reaches into its private `_lowlevel_server` (mcp pinned `<3`).
