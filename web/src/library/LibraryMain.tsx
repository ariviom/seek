import { useState } from "react";
import type { Channel, Group, Scope } from "@/lib/api";
import { Button } from "@/components/ui/button";
import type { Selection } from "@/lib/url-state";
import { AddChannelDialog } from "./AddChannelDialog";
import { NewGroupDialog } from "./NewGroupDialog";
import { ChannelPage } from "./ChannelPage";
import { GroupPage } from "./GroupPage";

export function LibraryMain({
  channels,
  groups,
  selection,
  select,
  reloadChannels,
  reloadGroups,
  onNewChat,
}: {
  channels: Channel[] | null;
  groups: Group[] | null;
  selection: Selection;
  select: (selection: Selection) => void;
  reloadChannels: () => Promise<void>;
  reloadGroups: () => Promise<void>;
  onNewChat: (scope: Scope) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [creating, setCreating] = useState(false);

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
        refresh={refresh}
        onNewChat={onNewChat}
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

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">Pick a channel or group, or add one.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
          Add channel
        </Button>
        <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
          New group
        </Button>
      </div>
      <AddChannelDialog
        open={adding}
        onOpenChange={setAdding}
        onAdded={(added) => {
          void reloadChannels();
          select({ channel: added.id, group: undefined, tab: "channels" });
        }}
      />
      <NewGroupDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(created) => {
          void reloadGroups();
          select({ group: created.id, channel: undefined, tab: "groups" });
        }}
      />
    </div>
  );
}
