import type { Channel, Group, Playlist, Scope, ScopeKind } from "@/lib/api";

// A Group, Channel, or Playlist as it is now: its name, the Channels that answer, how many Videos are searchable in
// it, and why a new chat can't start there, if it can't.
export type LiveScope = Scope & {
  name: string;
  // `videos` is null for a Playlist's creators: the Playlist's own count is the one that is listed.
  members: { id: number; name: string; videos: number | null; avatar_url: string | null }[];
  videos: number;
  unavailable: string | null;
};

// The glossary term for each kind.
export const scopeNoun: Record<ScopeKind, string> = { group: "Group", channel: "Channel", playlist: "Playlist" };

export function scopeKey(scope: Scope): string {
  return `${scope.kind}:${scope.id}`;
}

// Null when the Group, Channel, or Playlist is gone, or the lists haven't loaded yet.
export function liveScope(
  scope: Scope,
  groups: Group[] | null,
  channels: Channel[] | null,
  playlists: Playlist[] | null,
): LiveScope | null {
  if (groups === null || channels === null || playlists === null) return null;
  if (scope.kind === "group") {
    const group = groups.find((g) => g.id === scope.id);
    if (group === undefined) return null;
    const members = group.channels.map((member) => {
      const channel = channels.find((c) => c.id === member.id);
      return { ...member, videos: channel?.indexed_videos ?? 0, avatar_url: channel?.avatar_url ?? null };
    });
    return {
      ...scope,
      name: group.name,
      members,
      videos: members.reduce((ready, member) => ready + member.videos, 0),
      unavailable: members.length === 0 ? "This group has no channels yet, so nobody can answer." : null,
    };
  }
  if (scope.kind === "playlist") {
    const playlist = playlists.find((p) => p.id === scope.id);
    if (playlist === undefined) return null;
    return {
      ...scope,
      name: playlist.name,
      members: playlist.creators.map((creator) => ({ ...creator, videos: null })),
      videos: playlist.indexed_videos,
      unavailable: !playlist.indexed
        ? "This playlist is paused, so it can’t answer."
        : playlist.creators.length === 0
          ? "This playlist has no videos yet, so nothing can answer. Sync it on its page."
          : null,
    };
  }
  const channel = channels.find((c) => c.id === scope.id);
  if (channel === undefined) return null;
  return {
    ...scope,
    name: channel.name,
    members: [{ id: channel.id, name: channel.name, videos: channel.indexed_videos, avatar_url: channel.avatar_url }],
    videos: channel.indexed_videos,
    unavailable: channel.indexed ? null : "This channel is paused, so it can’t answer. Resume it on its page.",
  };
}
