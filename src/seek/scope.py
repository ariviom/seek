"""The scope of a Conversation and the tools bound to it: one Group of Channels, or one Channel on its own."""

from dataclasses import dataclass
from typing import Literal

type ScopeKind = Literal["group", "channel"]


@dataclass(frozen=True)
class Scope:
    kind: ScopeKind
    id: int


# The glossary term for each kind, for messages.
SCOPE_NOUN: dict[ScopeKind, str] = {"group": "Group", "channel": "Channel"}


# Matches a row of the channels table when no scope is given, or the Channel is the scope, or the Channel belongs to
# the scope's Group. Bind :scope_kind and :scope_id from `scope_params`.
CHANNEL_IN_SCOPE = """(
    :scope_kind IS NULL
    OR (:scope_kind = 'channel' AND channels.id = :scope_id)
    OR (:scope_kind = 'group' AND channels.id IN (SELECT channel_id FROM group_channels WHERE group_id = :scope_id))
)"""


def scope_params(scope: Scope | None) -> dict[str, object]:
    return {"scope_kind": scope and scope.kind, "scope_id": scope and scope.id}
