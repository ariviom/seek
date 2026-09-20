"""A scripted Anthropic Messages endpoint, for driving the real SDK without a provider.

Responses are server-sent events in the shape the streaming API sends, so the SDK's own accumulator
builds the final message; nothing here reimplements what the SDK does with a stream.
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


@dataclass(frozen=True)
class ToolUse:
    call_id: str
    name: str
    arguments: dict[str, object]


def _frames(events: Sequence[tuple[str, dict[str, object]]]) -> bytes:
    return b"".join(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in events)


def answer(
    text: str = "",
    *,
    tools: Sequence[ToolUse] = (),
    stop_reason: str = "end_turn",
    model: str = "claude-sonnet-5",
    input_tokens: int = 100,
    output_tokens: int = 20,
    cache_read_tokens: int = 0,
) -> bytes:
    """One streamed response: optional text, then any tool uses, then the stop reason and usage."""
    events: list[tuple[str, dict[str, object]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": 1,
                        "cache_read_input_tokens": cache_read_tokens,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        )
    ]
    index = 0
    if text:
        events += [
            ("content_block_start", {"type": "content_block_start", "index": index,
                                     "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": index,
                                     "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": index}),
        ]
        index += 1
    for use in tools:
        events += [
            ("content_block_start", {"type": "content_block_start", "index": index,
                                     "content_block": {"type": "tool_use", "id": use.call_id,
                                                       "name": use.name, "input": {}}}),
            ("content_block_delta", {"type": "content_block_delta", "index": index,
                                     "delta": {"type": "input_json_delta",
                                               "partial_json": json.dumps(use.arguments)}}),
            ("content_block_stop", {"type": "content_block_stop", "index": index}),
        ]
        index += 1
    events += [
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                           "usage": {"output_tokens": output_tokens}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return _frames(events)


@dataclass
class Provider:
    """Answers each request with the next scripted response, repeating the last one for anything after.

    `bodies` keeps what the SDK actually sent, which is how the request shape is checked. Install it with
    `monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())`: the hook is a plain function, so
    the transport's own client arrives as its first argument.
    """

    script: list[bytes | int] = field(default_factory=list)
    bodies: list[Any] = field(default_factory=list)
    requests: list[httpx2.Request] = field(default_factory=list)

    def hook(self) -> Callable[..., Awaitable[httpx2.Response]]:
        async def send(
            client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: object
        ) -> httpx2.Response:
            self.requests.append(request)
            self.bodies.append(json.loads(request.content))
            scripted = self.script[min(len(self.bodies) - 1, len(self.script) - 1)]
            if isinstance(scripted, int):
                return httpx2.Response(
                    scripted,
                    json={"type": "error", "error": {"type": "api_error", "message": "scripted failure"}},
                    request=request,
                )
            return httpx2.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=self._body(scripted),
                request=request,
            )

        return send

    async def _body(self, frames: bytes) -> AsyncIterator[bytes]:
        # One frame at a time, so a reader that stops early leaves the rest unsent.
        for frame in frames.split(b"\n\n"):
            if frame:
                yield frame + b"\n\n"
