"""The ChatEngine adapter: the local Claude CLI, driven through the Claude Agent SDK and locked down to mentor tools."""

import contextlib
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    CLINotFoundError,
    Message,
    ResultMessage,
    StreamEvent,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from claude_agent_sdk.types import McpSdkServerConfig

from mentor.ports import ChatDone, ChatEvent, ChatFailed, ChatRequest, TextDelta, ToolCall, ToolResult

TOOL_SERVER_NAME = "mentor"
# MCP resource tools the CLI adds whenever an MCP server is configured, even with built-in tools off. The model still
# sees them listed, but calls are denied (checked against Claude Code 2.x on 2026-09-13).
MCP_RESOURCE_TOOLS = ("ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool")
# Model turns (each a response, usually with tool calls) before the answer is cut off.
MAX_TURNS = 30
_CLI_MISSING = "The Claude CLI was not found; install Claude Code and log in with `claude`"


def chat_options(request: ChatRequest, working_directory: Path, cli_path: Path | None) -> ClaudeAgentOptions:
    """Options that leave the model nothing but the request's tools.

    allowed_tools alone only skips permission prompts, so every other way in is closed too: no built-in tools, no MCP
    servers but ours, no settings files (and with them no hooks, plugins, or CLAUDE.md), no skills or agents, anything
    not pre-approved denied, and an empty working directory.
    """
    server: McpSdkServerConfig = {
        "type": "sdk",
        "name": TOOL_SERVER_NAME,
        # The low-level server behind MCPServer; mcp's own in-memory client reaches it the same way.
        "instance": request.tools._lowlevel_server,  # noqa: SLF001
    }
    return ClaudeAgentOptions(
        tools=[],
        mcp_servers={TOOL_SERVER_NAME: server},
        strict_mcp_config=True,
        allowed_tools=[f"mcp__{TOOL_SERVER_NAME}__{name}" for name in request.tool_names],
        disallowed_tools=list(MCP_RESOURCE_TOOLS),
        permission_mode="dontAsk",
        setting_sources=[],
        skills=[],
        plugins=[],
        agents=None,
        hooks=None,
        cwd=working_directory,
        cli_path=cli_path,
        system_prompt=request.system_prompt,
        model=request.model,
        resume=request.resume_session_id,
        max_turns=MAX_TURNS,
        include_partial_messages=True,
        env={"CLAUDE_AGENT_SDK_CLIENT_APP": "mentor"},
    )


def chat_events(message: Message) -> list[ChatEvent]:
    """The ChatEvents in one SDK message. Answer text comes from the streamed deltas, not the finished message."""
    match message:
        case StreamEvent(event=event, parent_tool_use_id=None):
            delta = event.get("delta", {})
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                return [TextDelta(delta["text"])]
            return []
        case AssistantMessage(content=blocks):
            # Named as the tools are, without the CLI's mcp__mentor__ prefix.
            prefix = f"mcp__{TOOL_SERVER_NAME}__"
            return [
                ToolCall(b.id, b.name.removeprefix(prefix), b.input) for b in blocks if isinstance(b, ToolUseBlock)
            ]
        case UserMessage(content=list(blocks)):
            return [
                ToolResult(b.tool_use_id, _result_text(b.content), is_error=bool(b.is_error))
                for b in blocks
                if isinstance(b, ToolResultBlock)
            ]
        case ResultMessage(is_error=False, session_id=session_id):
            return [ChatDone(session_id)]
        case ResultMessage(result=result, errors=errors, subtype=subtype):
            return [ChatFailed(result or "; ".join(errors or []) or f"Claude Code stopped: {subtype}")]
    return []


def _result_text(content: str | list[dict[str, object]] | None) -> str:
    if content is None or isinstance(content, str):
        return content or ""
    return "\n".join(str(part["text"]) for part in content if part.get("type") == "text")


class ClaudeChatEngine:
    def __init__(self, working_directory: Path, cli_path: Path | None) -> None:
        """cli_path is the installed Claude CLI, or None when there is none; the SDK's bundled copy is never used."""
        # Kept empty: the model has no file tools, and nothing there should shape a session.
        self._working_directory = working_directory
        self._cli_path = cli_path

    async def stream(self, request: ChatRequest) -> AsyncGenerator[ChatEvent]:
        if self._cli_path is None:
            yield ChatFailed(_CLI_MISSING)
            return
        self._working_directory.mkdir(parents=True, exist_ok=True)
        options = chat_options(request, self._working_directory, self._cli_path)
        try:
            # Closed when this stream is, which stops the CLI process. query is an async generator, though typed as an
            # iterator.
            messages = cast(AsyncGenerator[Message], query(prompt=request.message, options=options))
            async with contextlib.aclosing(messages):
                async for message in messages:
                    for event in chat_events(message):
                        yield event
        except CLINotFoundError:
            yield ChatFailed(_CLI_MISSING)
        except ClaudeSDKError as e:
            yield ChatFailed(f"Claude Code failed: {e}")
