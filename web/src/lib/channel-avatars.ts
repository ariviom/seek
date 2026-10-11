import { createContext, useContext } from "react";
import type { Channel, Playlist } from "@/lib/api";

// Each Channel's avatar by id, from the lists App already loads, for the views whose payload names a Channel only by
// id (Citations, search results, Group members, a Playlist's Videos). The Playlists bring their creators, so a
// Channel outside the Library has its avatar too.
export const ChannelAvatars = createContext<ReadonlyMap<number, string>>(new Map());

export function avatarsOf(
  channels: Channel[] | null,
  playlists: Playlist[] | null = null,
): ReadonlyMap<number, string> {
  const avatars = new Map<number, string>();
  const creators = (playlists ?? []).flatMap((playlist) => playlist.creators);
  for (const channel of [...creators, ...(channels ?? [])]) {
    if (channel.avatar_url !== null) avatars.set(channel.id, channel.avatar_url);
  }
  return avatars;
}

export function useChannelAvatars(): (channelId: number | null) => string | null {
  const avatars = useContext(ChannelAvatars);
  return (channelId) => (channelId === null ? null : (avatars.get(channelId) ?? null));
}
