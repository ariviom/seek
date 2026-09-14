"""The ChatEngine adapter: the local Claude CLI, driven through the Claude Agent SDK and locked down to mentor tools."""

import asyncio
import contextlib
import json
import time
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
    get_session_info,
    query,
)
from claude_agent_sdk.types import McpSdkServerConfig

from mentor.ports import (
    ChatDone,
    ChatEngineStatus,
    ChatEvent,
    ChatFailed,
    ChatRequest,
    TextDelta,
    ToolCall,
    ToolResult,
)

TOOL_SERVER_NAME = "mentor"
# MCP resource tools the CLI adds whenever an MCP server is configured, even with built-in tools off. The model still
# sees them listed, but calls are denied (checked against Claude Code 2.x on 2026-09-13).
MCP_RESOURCE_TOOLS = ("ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool")
# Model turns (each a response, usually with tool calls) before the answer is cut off.
MAX_TURNS = 30
# How the CLI refuses to resume a session it no longer has or can't read (Claude Code 2.1.270).
_RESUME_FAILURES = ("No conversation found with session ID", "Failed to resume session", "resume load failed")
# The most of a Conversation replayed into a new session; the model's context holds much more, but tools need room.
REPLAY_CHARACTER_LIMIT = 100_000
STATUS_TIMEOUT_SECONDS = 10
STATUS_CACHE_SECONDS = 30


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
            reason = result or "; ".join(errors or []) or f"Claude Code stopped: {subtype}"
            return [ChatFailed(reason, session_lost=_is_resume_failure(reason))]
    return []


def _is_resume_failure(text: str) -> bool:
    return any(message in text for message in _RESUME_FAILURES)


def _result_text(content: str | list[dict[str, object]] | None) -> str:
    if content is None or isinstance(content, str):
        return content or ""
    return "\n".join(str(part["text"]) for part in content if part.get("type") == "text")


def prompt(request: ChatRequest) -> str:
    """The message, preceded by the Conversation so far when there is no session that already holds it.

    Only the most recent messages that fit REPLAY_CHARACTER_LIMIT are replayed, so a long Conversation still fits.
    """
    if request.resume_session_id is not None or not request.history:
        return request.message
    replayed: list[str] = []
    size = 0
    for past in reversed(request.history):
        line = f"{'User' if past.role == 'user' else 'You'}: {past.content}"
        size += len(line)
        if size > REPLAY_CHARACTER_LIMIT and replayed:
            replayed.append("(Earlier messages left out.)")
            break
        replayed.append(line)
    earlier = "\n\n".join(reversed(replayed))
    return (
        "This Conversation's earlier messages aren't in this session, so here they are for context (a question with "
        "no answer after it went unanswered). Cite only what the tools return now.\n\n"
        f"<earlier_conversation>\n{earlier}\n</earlier_conversation>\n\n{request.message}"
    )


def failure(error: ClaudeSDKError) -> ChatFailed:
    """The SDK error as a failed turn, noting whether the session to resume couldn't be."""
    return ChatFailed(f"Claude Code failed: {error}", session_lost=_is_resume_failure(str(error)))


class ClaudeChatEngine:
    def __init__(self, working_directory: Path, cli_path: Path | None) -> None:
        """cli_path is the installed Claude CLI, or None when there is none; the SDK's bundled copy is never used."""
        # Kept empty: the model has no file tools, and nothing there should shape a session.
        self._working_directory = working_directory
        self._cli_path = cli_path
        self._status: tuple[float, ChatEngineStatus] | None = None

    async def stream(self, request: ChatRequest) -> AsyncGenerator[ChatEvent]:
        if self._cli_path is None:
            yield ChatFailed(self._missing())
            return
        self._working_directory.mkdir(parents=True, exist_ok=True)
        if request.resume_session_id is not None and not await asyncio.to_thread(
            get_session_info, request.resume_session_id, str(self._working_directory)
        ):
            # Checked up front: the CLI's own refusal is an error message whose wording may change.
            yield ChatFailed(f"Claude session {request.resume_session_id} no longer exists", session_lost=True)
            return
        options = chat_options(request, self._working_directory, self._cli_path)
        try:
            # Closed when this stream is, which stops the CLI process. query is an async generator, though typed as an
            # iterator.
            messages = cast(AsyncGenerator[Message], query(prompt=prompt(request), options=options))
            async with contextlib.aclosing(messages):
                async for message in messages:
                    for event in chat_events(message):
                        yield event
        except CLINotFoundError:
            yield ChatFailed(self._missing())
        except ClaudeSDKError as e:
            yield failure(e)

    def _missing(self) -> str:
        where = f" at {self._cli_path}" if self._cli_path else " on PATH"
        return (
            f"The Claude CLI was not found{where}; install Claude Code and log in with `claude`, or set "
            "claude_cli_path in mentor's config"
        )

    async def status(self) -> ChatEngineStatus:
        """Asks the CLI whether it is logged in, which costs no tokens. Answers are reused for STATUS_CACHE_SECONDS."""
        now = time.monotonic()
        if self._status is None or now - self._status[0] > STATUS_CACHE_SECONDS:
            self._status = (now, await self._probe())
        return self._status[1]

    async def _probe(self) -> ChatEngineStatus:
        cli = str(self._cli_path) if self._cli_path else None
        if self._cli_path is None or not self._cli_path.is_file():
            return ChatEngineStatus("missing", cli, self._missing())
        try:
            process = await asyncio.create_subprocess_exec(
                self._cli_path,
                "auth",
                "status",
                "--json",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as e:
            return ChatEngineStatus("unknown", cli, f"Couldn't run `claude auth status`: {e}")
        try:
            output, _ = await asyncio.wait_for(process.communicate(), STATUS_TIMEOUT_SECONDS)
        except TimeoutError:
            return ChatEngineStatus("unknown", cli, f"`claude auth status` didn't answer within {STATUS_TIMEOUT_SECONDS} s")
        finally:
            # Also when the Health request is cancelled.
            if process.returncode is None:
                process.kill()
                await process.wait()
        try:
            auth = json.loads(output)
            logged_in, api_key = auth.get("loggedIn"), auth.get("apiKeySource")
        except (ValueError, AttributeError):
            return ChatEngineStatus("unknown", cli, "`claude auth status` didn't answer with its usual JSON")
        if api_key:
            # The chat inherits mentor's environment, so a key there bills the API instead of the subscription.
            return ChatEngineStatus(
                "api_key", cli, f"Claude Code would use the API key from {api_key}, not your subscription; unset it for mentor"
            )
        if logged_in is True:
            return ChatEngineStatus("ready", cli)
        return ChatEngineStatus("logged_out", cli, "Claude Code isn't logged in; run `claude auth login` on the server")
