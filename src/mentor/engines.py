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

# A Conversation pinned before engines were selectable holds a Claude CLI alias. A pin is a deliberate
# choice, so it is translated rather than dropped; anything untranslatable is an error, never a guess.
_ALIAS_MODELS: dict[str, str] = {
    "sonnet": API_MODELS["fast"],
    "opus": API_MODELS["deep"],
    "haiku": "claude-haiku-4-5",
}

ENGINE_LABEL: dict[EngineName, str] = {"api": "the Anthropic API", "cli": "the Claude CLI"}

# Model turns (each a response, usually with tool calls) before the answer is cut off. Both engines share it.
MAX_TURNS = 30


def resolve_model(engine: EngineName, pin: str | None, choice: ModelChoice) -> str:
    """The model identifier for this turn: the Conversation's pin if it has one, else the preferred choice.

    Raises Conflict when a pin cannot be expressed on this engine, rather than discarding it silently.
    """
    if pin is None:
        return API_MODELS[choice] if engine == "api" else CLI_MODELS[choice]
    if engine == "cli":
        return pin
    if pin in _ALIAS_MODELS:
        return _ALIAS_MODELS[pin]
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
    add instead of quietly running the other engine. Without one, a stored key means the API engine even
    if that key is invalid: reporting the key is more useful than billing the Claude CLI behind the user's
    back. Only chat depends on this; search, the Library and Syncs never ask.
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
        raise Conflict(
            "No chat engine is ready: add an Anthropic API key, or install the Claude CLI and log in with "
            f"`claude`. {statuses['cli'].message or ''}".strip()
        )
    status = statuses[engine]
    if status.state == "ready":
        return engine
    chosen = "The chat engine you chose" if preference is not None else "The chat engine Mentor picked"
    raise Conflict(f"{chosen}, {ENGINE_LABEL[engine]}, can't answer: {status.message or status.state}")
