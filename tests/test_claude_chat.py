from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from mcp.server.mcpserver import MCPServer

from mentor.claude_chat import chat_events, chat_options
from mentor.ports import ChatDone, ChatFailed, ChatRequest, TextDelta, ToolCall, ToolResult


def request(**changes: object) -> ChatRequest:
    fields: dict[str, object] = {
        "message": "How do I sharpen a chisel?",
        "system_prompt": "Answer only from Segments.",
        "model": None,
        "resume_session_id": None,
        "tools": MCPServer("mentor"),
        "tool_names": ("list_groups", "search", "expand", "get_video"),
    }
    return ChatRequest(**(fields | changes))  # type: ignore[arg-type]


def test_the_model_can_use_nothing_but_the_requests_mentor_tools(tmp_path: Path) -> None:
    tools = MCPServer("mentor")

    options = chat_options(request(tools=tools), tmp_path / "chat", cli_path=None)

    # Built-in tools off, and only our in-process server, strictly.
    assert options.tools == []
    assert options.mcp_servers == {
        "mentor": {"type": "sdk", "name": "mentor", "instance": tools._lowlevel_server}  # noqa: SLF001
    }
    assert options.strict_mcp_config is True
    assert options.allowed_tools == [
        "mcp__mentor__list_groups",
        "mcp__mentor__search",
        "mcp__mentor__expand",
        "mcp__mentor__get_video",
    ]
    # The MCP resource tools the CLI adds alongside any MCP server are removed, and anything else not pre-approved
    # is denied rather than prompted for.
    assert options.disallowed_tools == ["ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool"]
    assert options.permission_mode == "dontAsk"
    # No settings files (so no hooks, plugins, or CLAUDE.md from them), skills, plugins, or agents.
    assert (options.setting_sources, options.skills, options.plugins) == ([], [], [])
    assert (options.agents, options.hooks) == (None, None)
    assert options.cwd == tmp_path / "chat"


def test_sdk_messages_become_chat_events() -> None:
    def delta(event: dict[str, object], parent: str | None = None) -> StreamEvent:
        return StreamEvent(uuid="u", session_id="s", event=event, parent_tool_use_id=parent)

    text = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hone "}}
    result = {"duration_ms": 1, "duration_api_ms": 1, "num_turns": 2, "session_id": "session-9"}

    assert chat_events(delta(text)) == [TextDelta("Hone ")]
    # Deltas that aren't answer text, or come from a subagent, are not.
    assert chat_events(delta({"type": "content_block_delta", "delta": {"type": "input_json_delta"}})) == []
    assert chat_events(delta(text, parent="call-0")) == []
    assert chat_events(
        AssistantMessage(
            content=[
                TextBlock("Hone "),
                ToolUseBlock(id="call-1", name="mcp__mentor__search", input={"query": "hone"}),
            ],
            model="claude-sonnet-5",
        )
    ) == [ToolCall("call-1", "search", {"query": "hone"})]
    assert chat_events(
        UserMessage(
            content=[
                ToolResultBlock(tool_use_id="call-1", content=[{"type": "text", "text": "[]"}], is_error=None),
                ToolResultBlock(tool_use_id="call-2", content="Segment 9 not found", is_error=True),
            ]
        )
    ) == [ToolResult("call-1", "[]", is_error=False), ToolResult("call-2", "Segment 9 not found", is_error=True)]
    assert chat_events(UserMessage(content="a plain prompt")) == []
    assert chat_events(ResultMessage(subtype="success", is_error=False, **result)) == [ChatDone("session-9")]  # type: ignore[arg-type]
    assert chat_events(
        ResultMessage(subtype="success", is_error=True, result="Not logged in · Please run /login", **result)  # type: ignore[arg-type]
    ) == [ChatFailed("Not logged in · Please run /login")]
    assert chat_events(ResultMessage(subtype="error_max_turns", is_error=True, **result)) == [  # type: ignore[arg-type]
        ChatFailed("Claude Code stopped: error_max_turns")
    ]
