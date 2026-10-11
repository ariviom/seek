"""The scope of a Conversation and the tools bound to it: one Group of Channels, one Channel on its own, or one
Playlist."""

from dataclasses import dataclass
from typing import Literal

type ScopeKind = Literal["group", "channel", "playlist"]


@dataclass(frozen=True)
class Scope:
    kind: ScopeKind
    id: int


# The glossary term for each kind, for messages.
SCOPE_NOUN: dict[ScopeKind, str] = {"group": "Group", "channel": "Channel", "playlist": "Playlist"}

_ACTIVE_LIBRARY_CHANNEL = "(channels.indexed = 1 AND channels.in_library = 1)"

# The indexed Playlists that include a row of the videos table.
_ACTIVE_PLAYLISTS = """
    FROM playlist_videos JOIN playlists ON playlists.id = playlist_videos.playlist_id
    WHERE playlist_videos.video_id = videos.id AND playlists.indexed = 1
"""

# Matches a row of the videos table, beside the channels row it belongs to, when the Video is searchable (done, not
# excluded, and either on an indexed Channel in the Library or included in an indexed Playlist) and the scope covers
# it: no scope covers every searchable Video, a Channel its own, a Group its Channels', and a Playlist the ones it
# includes, whatever their Channels. Bind :scope_kind and :scope_id from `scope_params`.
VIDEO_IN_SCOPE = f"""(
    videos.pipeline_stage = 'done' AND videos.excluded_reason IS NULL
    AND (
        (:scope_kind IS NULL AND ({_ACTIVE_LIBRARY_CHANNEL} OR EXISTS (SELECT 1 {_ACTIVE_PLAYLISTS})))
        OR (:scope_kind = 'channel' AND {_ACTIVE_LIBRARY_CHANNEL} AND videos.channel_id = :scope_id)
        OR (:scope_kind = 'group' AND {_ACTIVE_LIBRARY_CHANNEL}
            AND videos.channel_id IN (SELECT channel_id FROM group_channels WHERE group_id = :scope_id))
        OR (:scope_kind = 'playlist' AND EXISTS (SELECT 1 {_ACTIVE_PLAYLISTS} AND playlists.id = :scope_id))
    )
)"""

# For a row of the videos table: the ids of the indexed Playlists that include it, as a JSON array in id order.
ACTIVE_PLAYLIST_IDS = f"""(
    SELECT json_group_array(id) FROM (SELECT playlists.id {_ACTIVE_PLAYLISTS} ORDER BY playlists.id)
)"""

# Matches a row of the channels table when the scope names the Channel, searchable or not: no scope names every
# Channel, a Channel itself, a Group its members, a Playlist the creators of its Videos. For listing a scope's
# Channels; what a scope covers is VIDEO_IN_SCOPE.
CHANNEL_IN_SCOPE = """(
    :scope_kind IS NULL
    OR (:scope_kind = 'channel' AND channels.id = :scope_id)
    OR (:scope_kind = 'group' AND channels.id IN (SELECT channel_id FROM group_channels WHERE group_id = :scope_id))
    OR (:scope_kind = 'playlist' AND channels.id IN (
        SELECT videos.channel_id FROM playlist_videos JOIN videos ON videos.id = playlist_videos.video_id
        WHERE playlist_videos.playlist_id = :scope_id
    ))
)"""


def scope_params(scope: Scope | None) -> dict[str, object]:
    return {"scope_kind": scope and scope.kind, "scope_id": scope and scope.id}
