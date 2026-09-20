"""Which engine answers a turn, and which model identifier that engine is given.

The two engines' model tables are deliberately separate: the Claude CLI takes aliases and the Anthropic
API takes full model ids, and a value from one table is never sent to the other (ADR 0004).
"""

from collections.abc import Mapping
from typing import Literal

from mentor.errors import Conflict
from mentor.ports import ChatEngineStatus, EngineName

type ModelChoice = Literal["fast", "deep"]

# The API default is explicit: the Claude CLI's "use your own default" has no API equivalent.
API_MODELS: dict[ModelChoice, str] = {"fast": "claude-sonnet-5", "deep": "claude-opus-5"}
CLI_MODELS: dict[ModelChoice, str] = {"fast": "sonnet", "deep": "opus"}

# A pin made on one engine has to be expressed in the other's vocabulary when the engine changes: a
# Conversation pinned before engines were selectable holds a Claude CLI alias, and one pinned on the API
# engine holds a full model id. A pin is a deliberate choice, so it is translated rather than dropped, and
# anything untranslatable is an error rather than a guess. Ids checked against the Claude API on 2026-09-20.
_CLI_TO_API: dict[str, str] = {
    "sonnet": API_MODELS["fast"],
    "opus": API_MODELS["deep"],
    "haiku": "claude-haiku-4-5",
}
_API_TO_CLI: dict[str, str] = {api: cli for cli, api in _CLI_TO_API.items()}

ENGINE_LABEL: dict[EngineName, str] = {"api": "the Anthropic API", "cli": "the Claude CLI"}

# Read-only project and web context are Claude CLI built-ins, not MCP tools (ADR 0004).
NO_API_CONTEXT = (
    "This Conversation was created with project or web access, which only the Claude CLI engine can "
    "provide. Switch this chat to the Claude CLI, or start a new Conversation without them."
)

# Model turns (each a response, usually with tool calls) before the answer is cut off. Both engines share it.
MAX_TURNS = 30


def resolve_model(engine: EngineName, pin: str | None, choice: ModelChoice) -> str:
    """The model identifier for this turn: the Conversation's pin if it has one, else the preferred choice.

    Raises Conflict when a pin cannot be expressed on this engine, rather than discarding it silently.
    """
    if pin is None:
        return API_MODELS[choice] if engine == "api" else CLI_MODELS[choice]
    if engine == "cli":
        # The CLI takes aliases and full names alike, so anything it doesn't know is left to it to reject.
        return _API_TO_CLI.get(pin, pin)
    if pin in _CLI_TO_API:
        return _CLI_TO_API[pin]
    if pin.startswith("claude-"):
        return pin
    raise Conflict(
        f"This Conversation is pinned to the model {pin!r}, which {ENGINE_LABEL['api']} doesn't offer. "
        "Choose another model for it, or switch this chat to the Claude CLI."
    )


def active_engine(
    preference: EngineName | None, statuses: Mapping[EngineName, ChatEngineStatus]
) -> EngineName | None:
    """The engine a turn would use, or None when nothing is available.

    An explicit preference is honoured even when its requirement is missing, so the turn explains what to
    add instead of quietly running the other engine. Without one, anything but a confirmed absence of a key
    means the API engine: an invalid key, or a credential store that cannot be read, is worth reporting
    rather than billing the Claude CLI behind the user's back. Only chat depends on this; search, the
    Library and Syncs never ask.
    """
    if preference is not None:
        return preference
    if statuses["api"].state != "no_key":
        return "api"
    if statuses["cli"].state == "ready":
        return "cli"
    return None


def choose_engine(
    preference: EngineName | None, statuses: Mapping[EngineName, ChatEngineStatus]
) -> EngineName:
    """The engine for this turn. Raises Conflict, with what to add, when it cannot answer."""
    engine = active_engine(preference, statuses)
    if engine is None:
        # Both engines' own instructions, so the dead end says where to get a key as well as a CLI.
        missing = " ".join(s.message for s in statuses.values() if s.message)
        raise Conflict(f"No chat engine is ready. {missing}".strip())
    status = statuses[engine]
    if status.state == "ready":
        return engine
    chosen = "The chat engine you chose" if preference is not None else "The chat engine Mentor picked"
    raise Conflict(f"{chosen}, {ENGINE_LABEL[engine]}, can't answer: {status.message or status.state}")
