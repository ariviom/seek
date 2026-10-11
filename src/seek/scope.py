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


# Matches a row of the videos table, beside the channels row it belongs to, when the Video is searchable (done, not
# excluded, on an indexed Channel in the Library) and the scope covers it: no scope covers every searchable Video, a Channel its
# own, a Group its Channels'. Bind :scope_kind and :scope_id from `scope_params`.
VIDEO_IN_SCOPE = """(
    videos.pipeline_stage = 'done' AND videos.excluded_reason IS NULL
    AND channels.indexed = 1 AND channels.in_library = 1
    AND (
        :scope_kind IS NULL
        OR (:scope_kind = 'channel' AND videos.channel_id = :scope_id)
        OR (:scope_kind = 'group'
            AND videos.channel_id IN (SELECT channel_id FROM group_channels WHERE group_id = :scope_id))
    )
)"""

# Matches a row of the channels table when the scope names the Channel, searchable or not: no scope names every
# Channel, a Channel itself, a Group its members. For listing a scope's Channels; what a scope covers is
# VIDEO_IN_SCOPE.
CHANNEL_IN_SCOPE = """(
    :scope_kind IS NULL
    OR (:scope_kind = 'channel' AND channels.id = :scope_id)
    OR (:scope_kind = 'group' AND channels.id IN (SELECT channel_id FROM group_channels WHERE group_id = :scope_id))
)"""


def scope_params(scope: Scope | None) -> dict[str, object]:
    return {"scope_kind": scope and scope.kind, "scope_id": scope and scope.id}
