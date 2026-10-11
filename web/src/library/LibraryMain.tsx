import type { Channel, Group, Playlist, Scope, Sync } from "@/lib/api";
import type { Selection } from "@/lib/url-state";
import { PaneMessage } from "@/components/PaneMessage";
import { ChannelPage } from "./ChannelPage";
import { GroupPage } from "./GroupPage";
import { PlaylistPage } from "./PlaylistPage";

export function LibraryMain({
  channels,
  groups,
  playlists,
  syncs,
  selection,
  select,
  reloadChannels,
  reloadGroups,
  reloadPlaylists,
  onNewChat,
  onOpenSync,
}: {
  channels: Channel[] | null;
  groups: Group[] | null;
  playlists: Playlist[] | null;
  syncs: Sync[] | null;
  selection: Selection;
  select: (selection: Selection) => void;
  reloadChannels: () => Promise<void>;
  reloadGroups: () => Promise<void>;
  reloadPlaylists: () => Promise<void>;
  onNewChat: (scope: Scope) => void;
  onOpenSync: (syncId: number) => void;
}) {
  // Both lists are reloaded after any change: membership, renames, and deletions cross between them.
  const refresh = async () => {
    await Promise.all([reloadChannels(), reloadGroups()]);
  };

  const channel = channels?.find((c) => c.id === selection.channel);
  const group = groups?.find((g) => g.id === selection.group);
  const playlist = playlists?.find((p) => p.id === selection.playlist);

  if (channel !== undefined && groups !== null) {
    return (
      <ChannelPage
        key={channel.id}
        channel={channel}
        groups={groups}
        syncs={syncs}
        refresh={refresh}
        onNewChat={onNewChat}
        onOpenSync={onOpenSync}
        onRemoved={() => select({ channel: undefined })}
      />
    );
  }
  if (group !== undefined && channels !== null) {
    return (
      <GroupPage
        key={group.id}
        group={group}
        channels={channels}
        refresh={refresh}
        onNewChat={onNewChat}
        onDeleted={() => select({ group: undefined })}
      />
    );
  }

  if (playlist !== undefined) {
    return (
      <PlaylistPage
        key={playlist.id}
        playlist={playlist}
        syncs={syncs}
        refresh={reloadPlaylists}
        onOpenSync={onOpenSync}
      />
    );
  }

  return <PaneMessage>Pick a channel, group, or playlist, or add one from the list.</PaneMessage>;
}
