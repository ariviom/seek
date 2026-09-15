import type { Channel, Group, Scope } from "@/lib/api";

// A Group or Channel as it is now: its name, the Channels that answer with their Video counts, and why a new chat
// can't start there, if it can't.
export type LiveScope = Scope & {
  name: string;
  members: { id: number; name: string; videos: number }[];
  unavailable: string | null;
};

export function scopeKey(scope: Scope): string {
  return `${scope.kind}:${scope.id}`;
}

// Null when the Group or Channel is gone, or the lists haven't loaded yet.
export function liveScope(scope: Scope, groups: Group[] | null, channels: Channel[] | null): LiveScope | null {
  if (groups === null || channels === null) return null;
  if (scope.kind === "group") {
    const group = groups.find((g) => g.id === scope.id);
    if (group === undefined) return null;
    const members = group.channels.map((member) => ({
      ...member,
      videos: channels.find((c) => c.id === member.id)?.indexed_videos ?? 0,
    }));
    return {
      ...scope,
      name: group.name,
      members,
      unavailable: members.length === 0 ? "This group has no channels yet, so nobody can answer." : null,
    };
  }
  const channel = channels.find((c) => c.id === scope.id);
  if (channel === undefined) return null;
  return {
    ...scope,
    name: channel.name,
    members: [{ id: channel.id, name: channel.name, videos: channel.indexed_videos }],
    unavailable: channel.indexed ? null : "This channel is paused, so it can’t answer. Resume it on its page.",
  };
}
