# 12 — Web chat

**What to build:** Open a Mentor Group in the web UI, ask a question, and watch a grounded answer stream in with tool calls visible. It runs on the local Claude CLI through the Claude Agent SDK and can use mentor tools only. (Stories 36–40.)

**Blocked by:** 11 — MCP server

**Status:** ready-for-agent

- [ ] Claude Agent SDK ChatEngine adapter streams text deltas, tool calls, tool results, done, and error events
- [ ] Lockdown: `allowed_tools` alone is not enough. Built-in tools are disabled, only the in-process mentor MCP server is configured (strict), no user settings, skills, plugins, or hooks load, and it runs in a fixed empty working directory. Verify the option names against the installed SDK version
- [ ] In-process tools are bound server-side to the Conversation's Group; the model cannot widen scope
- [ ] Grounded-advisor system prompt per spec
- [ ] Conversation create (Group, model) and `POST message` returning an SSE stream; the user message persists before streaming; one turn per Conversation at a time
- [ ] Assistant messages persist on completion with durable citation data (Video id, seconds, Mentor and Video names); the Claude session id is stored
- [ ] UI chat view renders streaming text and tool calls
- [ ] API tests with FakeChatEngine assert every lockdown option and the Group binding it received, plus persistence
