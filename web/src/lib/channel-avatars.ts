import { createContext, useContext } from "react";
import type { Channel } from "@/lib/api";

// Each Channel's avatar by id, from the channels list App already loads, for the views whose payload names a Channel
// only by id (Citations, search results, Group members).
export const ChannelAvatars = createContext<ReadonlyMap<number, string>>(new Map());

export function avatarsOf(channels: Channel[] | null): ReadonlyMap<number, string> {
  const avatars = new Map<number, string>();
  for (const channel of channels ?? []) if (channel.avatar_url !== null) avatars.set(channel.id, channel.avatar_url);
  return avatars;
}

export function useChannelAvatars(): (channelId: number | null) => string | null {
  const avatars = useContext(ChannelAvatars);
  return (channelId) => (channelId === null ? null : (avatars.get(channelId) ?? null));
}
