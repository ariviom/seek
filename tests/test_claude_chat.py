from pathlib import Path
from uuid import uuid4

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ProcessError,
    ResultError,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from mcp.server.mcpserver import MCPServer

from mentor import claude_chat
from mentor.claude_chat import ClaudeChatEngine, chat_events, chat_options, failure, prompt
from mentor.ports import ChatDone, ChatFailed, ChatRequest, PastMessage, TextDelta, ToolCall, ToolResult


def request(**changes: object) -> ChatRequest:
    fields: dict[str, object] = {
        "message": "How do I sharpen a chisel?",
        "system_prompt": "Answer only from Segments.",
        "model": None,
        "resume_session_id": None,
        "history": (),
        "workspace": None,
        "web_access": False,
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


async def test_selected_project_and_web_resources_are_read_only_and_explicit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    options = chat_options(request(workspace=project, web_access=True), tmp_path / "chat", cli_path=None)

    assert options.tools == ["Read", "Glob", "Grep", "WebFetch", "WebSearch"]
    assert options.allowed_tools[-5:] == ["Read", "Glob", "Grep", "WebFetch", "WebSearch"]
    assert options.cwd == project
    assert options.setting_sources == []
    assert options.hooks is not None
    [matcher] = options.hooks["PreToolUse"]
    assert matcher.matcher == "Read|Glob|Grep"
    [guard] = matcher.hooks
    inside = await guard(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "session",
            "transcript_path": "transcript",
            "cwd": str(project),
            "tool_name": "Read",
            "tool_input": {"file_path": str(project / "README.md")},
            "tool_use_id": "inside",
        },
        "inside",
        {"signal": None},
    )
    outside = await guard(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "session",
            "transcript_path": "transcript",
            "cwd": str(project),
            "tool_name": "Read",
            "tool_input": {"file_path": str(tmp_path / "secret.txt")},
            "tool_use_id": "outside",
        },
        "outside",
        {"signal": None},
    )
    assert inside == {}
    assert outside == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"This chat may read only the selected project directory: {project}",
        }
    }


def test_a_new_session_is_given_the_conversation_so_far_and_a_resumed_one_is_not() -> None:
    history = (PastMessage("user", "Which stone?"), PastMessage("assistant", "A 1000 grit waterstone."))

    fresh = prompt(request(history=history, message="And then?"))

    assert prompt(request(history=history, resume_session_id="session-1", message="And then?")) == "And then?"
    assert prompt(request(message="Which stone?")) == "Which stone?"
    assert fresh.endswith(
        "<earlier_conversation>\nUser: Which stone?\n\nYou: A 1000 grit waterstone.\n</earlier_conversation>\n\n"
        "And then?"
    )


def test_a_replay_keeps_the_most_recent_messages_that_fit() -> None:
    history = [PastMessage("user", "old " * 30_000), PastMessage("assistant", "recent answer")]

    replayed = prompt(request(history=history, message="Next?"))

    assert "(Earlier messages left out.)\n\nYou: recent answer" in replayed
    assert "old old" not in replayed


def test_a_session_the_cli_cant_resume_is_reported_as_lost() -> None:
    # The CLI's refusal reaches the SDK as a failed result: raised as a ResultError, or streamed as a result message.
    refused = {"subtype": "error_during_execution", "errors": ["No conversation found with session ID: abc"]}
    raised = failure(ResultError("Claude Code returned an error result: " + refused["errors"][0], refused))
    streamed = chat_events(
        ResultMessage(
            subtype="error_during_execution",
            is_error=True,
            errors=["Failed to resume session: abc"],
            duration_ms=1,
            duration_api_ms=0,
            num_turns=0,
            session_id="abc",
        )
    )
    other = failure(ProcessError("Command failed", exit_code=1))

    assert raised.session_lost and streamed == [ChatFailed("Failed to resume session: abc", session_lost=True)]
    assert (other.session_lost, other.message) == (False, "Claude Code failed: Command failed (exit code: 1)")


async def test_a_session_with_no_transcript_is_lost_before_the_cli_starts(tmp_path: Path) -> None:
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\nexit 1\n")
    cli.chmod(0o755)
    engine = ClaudeChatEngine(tmp_path / "chat", cli)

    events = [event async for event in engine.stream(request(resume_session_id=str(uuid4())))]

    assert [(type(e), getattr(e, "session_lost", None)) for e in events] == [(ChatFailed, True)]


@pytest.mark.parametrize(
    ("output", "state"),
    [
        ('{"loggedIn": true, "authMethod": "claude.ai", "apiKeySource": null}', "ready"),
        ('{"loggedIn": false}', "logged_out"),
        # The chat inherits mentor's environment, where an API key would be billed instead of the subscription.
        ('{"loggedIn": true, "apiKeySource": "ANTHROPIC_API_KEY"}', "api_key"),
        ("not json", "unknown"),
    ],
)
async def test_status_asks_the_cli_whether_it_is_logged_in(tmp_path: Path, output: str, state: str) -> None:
    cli = tmp_path / "claude"
    cli.write_text(f"#!/bin/sh\n[ \"$*\" = 'auth status --json' ] && echo '{output}'\n")
    cli.chmod(0o755)

    status = await ClaudeChatEngine(tmp_path / "chat", cli).status()

    assert (status.state, status.cli_path) == (state, str(cli))
    assert (status.message is None) == (state == "ready")


async def test_status_gives_up_on_a_cli_that_doesnt_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_chat, "STATUS_TIMEOUT_SECONDS", 0.2)
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\nexec sleep 30\n")
    cli.chmod(0o755)

    status = await ClaudeChatEngine(tmp_path / "chat", cli).status()

    assert status.state == "unknown" and "didn't answer" in (status.message or "")


@pytest.mark.parametrize("configured", [None, Path("/opt/nowhere/claude")])
async def test_status_and_turns_report_a_missing_cli(tmp_path: Path, configured: Path | None) -> None:
    engine = ClaudeChatEngine(tmp_path / "chat", configured)

    status = await engine.status()
    events = [event async for event in engine.stream(request())]

    where = f"at {configured}" if configured else "on PATH"
    assert (status.state, status.cli_path) == ("missing", configured and str(configured))
    assert status.message == (
        f"The Claude CLI was not found {where}; install Claude Code and log in with `claude`, or set claude_cli_path "
        "in mentor's config"
    )
    assert len(events) == 1 and isinstance(events[0], ChatFailed)


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
