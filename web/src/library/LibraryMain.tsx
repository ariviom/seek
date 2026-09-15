import type { Channel, Group, Scope, Sync } from "@/lib/api";
import type { Selection } from "@/lib/url-state";
import { ChannelPage } from "./ChannelPage";
import { GroupPage } from "./GroupPage";

export function LibraryMain({
  channels,
  groups,
  syncs,
  selection,
  select,
  reloadChannels,
  reloadGroups,
  onNewChat,
  onOpenSync,
}: {
  channels: Channel[] | null;
  groups: Group[] | null;
  syncs: Sync[] | null;
  selection: Selection;
  select: (selection: Selection) => void;
  reloadChannels: () => Promise<void>;
  reloadGroups: () => Promise<void>;
  onNewChat: (scope: Scope) => void;
  onOpenSync: (syncId: number) => void;
}) {
  // Both lists are reloaded after any change: membership, renames, and deletions cross between them.
  const refresh = async () => {
    await Promise.all([reloadChannels(), reloadGroups()]);
  };

  const channel = channels?.find((c) => c.id === selection.channel);
  const group = groups?.find((g) => g.id === selection.group);

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

  return <p className="text-sm text-muted-foreground">Pick a channel or group, or add one from the list.</p>;
}
