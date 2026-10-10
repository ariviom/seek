"""The ChatEngine adapter: Seek's own tool loop against the Anthropic API, with the stored key.

There is no provider-side session, so every turn replays the Conversation from our store (ADR 0004). The
tool schemas are translated from the scoped MCP server's own listing, so the two engines cannot drift.
"""

import contextlib
import json
import logging
from collections.abc import AsyncGenerator, Sequence

import anthropic
from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from seek.credentials import Credential, Credentials, suppressed_sdk_logs
from seek.engines import MAX_TURNS, NO_API_CONTEXT
from seek.ports import (
    ChatDone,
    ChatEngineStatus,
    ChatEvent,
    ChatFailed,
    ChatRequest,
    PastMessage,
    SecretsUnavailable,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolResult,
    UsageReported,
)

log = logging.getLogger(__name__)

# The provider is fixed, so no environment variable can redirect a turn to somewhere else.
BASE_URL = "https://api.anthropic.com"
# Streaming, so a long answer can't hit an HTTP timeout; the models allow more, but a chat answer is not a book.
MAX_OUTPUT_TOKENS = 16_000
# Long enough for a slow deep answer, short enough that a hung connection doesn't hold the turn forever.
REQUEST_TIMEOUT_SECONDS = 600.0
# The most of a Conversation replayed into a turn, mirroring the Claude CLI adapter's replay limit.
REPLAY_CHARACTER_LIMIT = 100_000
_TRUNCATED = "(Earlier messages in this Conversation were left out.)"

WHERE_TO_GET_A_KEY = "https://console.anthropic.com/settings/keys"
NO_KEY = f"Add an Anthropic API key to chat through the API; create one at {WHERE_TO_GET_A_KEY}"
INVALID_KEY = "The stored Anthropic API key was rejected. Replace it in Seek's settings."


async def tool_schemas(tools: MCPServer, allowed: Sequence[str]) -> list[ToolParam]:
    """The scoped server's own tools, in the provider's format; nothing outside `allowed` is offered.

    Cache control on the last one covers the whole tool list, which is identical on every turn.
    """
    permitted = set(allowed)
    schemas: list[ToolParam] = [
        ToolParam(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.input_schema,
        )
        for tool in await tools.list_tools()
        if tool.name in permitted
    ]
    if schemas:
        schemas[-1]["cache_control"] = {"type": "ephemeral"}
    return schemas


def replayed(history: Sequence[PastMessage], message: str) -> list[MessageParam]:
    """The turn's messages: the most recent history that fits the replay limit, then the new question.

    A question with no answer after it stays in place, so the model sees that it went unanswered.
    """
    kept: list[PastMessage] = []
    size = 0
    truncated = False
    for past in reversed(history):
        if not past.content.strip():
            continue
        size += len(past.content)
        if size > REPLAY_CHARACTER_LIMIT and kept:
            truncated = True
            break
        kept.append(past)
    kept.reverse()
    messages: list[MessageParam] = []
    # The provider's first message must be a user message, which truncation can otherwise cut away.
    if truncated or (kept and kept[0].role == "assistant"):
        messages.append({"role": "user", "content": _TRUNCATED})
    messages.extend({"role": past.role, "content": past.content} for past in kept)
    messages.append({"role": "user", "content": message})
    return messages


def _result_text(result: CallToolResult) -> str:
    """A tool's answer as the provider wants it: its text blocks, or its structured value if it had none.

    Never empty, because a tool_result block with no content tells the model nothing about what happened.
    """
    parts = [block.text for block in result.content if isinstance(block, TextContent)]
    if parts:
        return "\n".join(parts)
    if result.structured_content is not None:
        return json.dumps(result.structured_content)
    return "The tool returned nothing."


def failure_message(error: anthropic.APIError, key: str) -> str:
    """One sentence a friend can act on, never a stack trace.

    A rate limit or an overload says to retry, because neither says anything about the key. Anything else
    passes on what the provider said, with the key redacted in case the provider echoed it back.
    """
    if isinstance(error, anthropic.RateLimitError):
        return "The Anthropic API is rate limiting this key right now; wait a moment and ask again."
    if isinstance(error, anthropic.APIStatusError) and error.status_code in (500, 502, 503, 504, 529):
        return "The Anthropic API is overloaded or unavailable right now; ask again in a moment."
    if isinstance(error, anthropic.APIConnectionError):
        return "Seek couldn't reach the Anthropic API; check this machine's connection and ask again."
    if isinstance(error, anthropic.APIStatusError):
        body = error.body if isinstance(error.body, dict) else {}
        detail = body.get("error", {})
        said = detail.get("message") if isinstance(detail, dict) else None
        return f"The Anthropic API refused this request: {_redacted(said or error.message, key)}"
    return f"The Anthropic API request failed: {_redacted(str(error), key)}"


def _redacted(text: str, key: str) -> str:
    return text.replace(key, "the stored key")


class ApiEngine:
    """Answers a turn with the stored Anthropic key, running the tool loop itself.

    An authentication failure invalidates only the credential generation the turn used, so a key replaced
    while the turn was in flight keeps its own validation state.
    """

    def __init__(self, credentials: Credentials) -> None:
        self._credentials = credentials

    async def status(self) -> ChatEngineStatus:
        """Reads the last known credential state. Never calls the provider, so an offline start is honest."""
        try:
            stored = await self._credentials.status()
        except SecretsUnavailable as e:
            return ChatEngineStatus("api", "unknown", None, str(e))
        if not stored.present:
            return ChatEngineStatus("api", "no_key", None, NO_KEY)
        if stored.validity == "invalid":
            return ChatEngineStatus("api", "invalid_key", None, INVALID_KEY)
        return ChatEngineStatus("api", "ready", None)

    async def stream(self, request: ChatRequest) -> AsyncGenerator[ChatEvent]:
        # Chat refuses these before saving the question; this is the port's own guarantee, for any caller.
        if request.workspace is not None or request.web_access:
            yield ChatFailed(NO_API_CONTEXT)
            return
        try:
            credential = await self._credentials.current()
        except SecretsUnavailable as e:
            yield ChatFailed(str(e))
            return
        if credential is None:
            yield ChatFailed(NO_KEY)
            return
        if request.model is None:
            # Selection always resolves a model for this engine; a missing one would silently become the
            # provider's own default, which is not a choice the user made.
            yield ChatFailed("Seek didn't choose a model for this turn; set one in settings and ask again.")
            return
        with suppressed_sdk_logs():
            # aclosing, because an `async for` that ends early leaves the inner generator suspended,
            # so a stopped turn's SDK stream and connection would close whenever the loop got round to
            # finalising it rather than when the turn stopped.
            async with contextlib.aclosing(self._turn(request, credential, request.model)) as turn:
                async for event in turn:
                    yield event

    async def _turn(
        self, request: ChatRequest, credential: Credential, model: str
    ) -> AsyncGenerator[ChatEvent]:
        messages = replayed(request.history, request.message)
        tools = await tool_schemas(request.tools, request.tool_names)
        allowed = set(request.tool_names)
        # Per-request headers win over any SDK custom-header environment values.
        headers: dict[str, str | anthropic.Omit] = {
            "X-Api-Key": credential.key,
            "Authorization": anthropic.omit,
        }
        try:
            async with anthropic.AsyncAnthropic(
                api_key=credential.key, base_url=BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS
            ) as client:
                for _step in range(MAX_TURNS):
                    async with client.messages.stream(
                        model=model,
                        max_tokens=MAX_OUTPUT_TOKENS,
                        system=[
                            {
                                "type": "text",
                                "text": request.system_prompt,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                        thinking={"type": "adaptive"},
                        tools=tools,
                        messages=messages,
                        extra_headers=headers,
                    ) as stream:
                        async for event in stream:
                            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                                yield TextDelta(event.delta.text)
                        answer = await stream.get_final_message()
                    # Emitted before anything that could fail, so a later step's failure can't lose it.
                    yield UsageReported(
                        TokenUsage(
                            input_tokens=answer.usage.input_tokens or 0,
                            output_tokens=answer.usage.output_tokens or 0,
                            cache_read_tokens=answer.usage.cache_read_input_tokens or 0,
                        )
                    )
                    # Thinking and tool_use blocks go back unchanged: the provider rejects a continuation
                    # whose earlier steps were rewritten.
                    messages.append({"role": "assistant", "content": answer.content})
                    if answer.stop_reason == "pause_turn":
                        continue
                    if answer.stop_reason == "refusal":
                        yield ChatFailed("The model declined to answer this question.")
                        return
                    uses = [block for block in answer.content if block.type == "tool_use"]
                    if answer.stop_reason == "max_tokens":
                        # A truncated tool input parses as a plausible object; running it would be a guess.
                        yield ChatFailed(
                            "The answer reached the model's output limit before it finished; ask again in "
                            "smaller pieces."
                        )
                        return
                    if not uses:
                        yield ChatDone()
                        return
                    results: list[ToolResultBlockParam] = []
                    for use in uses:
                        arguments = use.input if isinstance(use.input, dict) else {}
                        yield ToolCall(use.id, use.name, arguments)
                        content, is_error = await self._call(request.tools, use.name, arguments, allowed)
                        yield ToolResult(use.id, content, is_error)
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": use.id,
                                "content": content,
                                "is_error": is_error,
                            }
                        )
                    messages.append({"role": "user", "content": results})
            yield ChatFailed(f"The answer needed more than {MAX_TURNS} steps, so Seek stopped it.")
        except anthropic.AuthenticationError:
            # Only this turn's generation: a key replaced or deleted meanwhile keeps its own state.
            await self._credentials.invalidate(credential.generation)
            yield ChatFailed(INVALID_KEY)
        except anthropic.APIError as e:
            log.warning("Anthropic API turn failed: %s", type(e).__name__)
            yield ChatFailed(failure_message(e, credential.key))

    @staticmethod
    async def _call(
        tools: MCPServer, name: str, arguments: dict[str, object], allowed: set[str]
    ) -> tuple[str, bool]:
        """One tool use, executed by the scoped server. A name it doesn't offer is refused, not searched for."""
        if name not in allowed:
            return f"This chat has no tool named {name}.", True
        try:
            result = await tools.call_tool(name, arguments)
        except ToolError as e:
            return str(e), True
        if not isinstance(result, CallToolResult):
            # An input-required result: Seek's own tools never ask for one, and the model cannot answer it.
            return f"The tool {name} asked for input this chat cannot supply.", True
        return _result_text(result), bool(result.is_error)
