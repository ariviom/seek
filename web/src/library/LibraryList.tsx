import type { Channel, Group, Sync } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Selection } from "@/lib/url-state";
import { ChannelList } from "./ChannelList";
import { GroupList } from "./GroupList";

export function LibraryList({
  channels,
  groups,
  syncs,
  selection,
  select,
  onAddChannel,
  onNewGroup,
}: {
  channels: Channel[] | null;
  groups: Group[] | null;
  syncs: Sync[] | null;
  selection: Selection;
  select: (selection: Selection) => void;
  onAddChannel: () => void;
  onNewGroup: () => void;
}) {
  const tab = selection.tab ?? "channels";

  return (
    <Tabs value={tab} onValueChange={(value) => select({ tab: value as "channels" | "groups" })}>
      <TabsList className="w-full">
        <TabsTrigger value="channels">Channels</TabsTrigger>
        <TabsTrigger value="groups">Groups</TabsTrigger>
      </TabsList>
      <TabsContent value="channels" className="mt-2 space-y-2">
        <Button variant="outline" size="sm" className="w-full" onClick={onAddChannel}>
          Add channel
        </Button>
        <ChannelList
          channels={channels ?? []}
          syncs={syncs}
          selectedId={selection.channel ?? null}
          onSelect={(channel) => select({ channel: channel.id, group: undefined, tab: "channels" })}
        />
      </TabsContent>
      <TabsContent value="groups" className="mt-2 space-y-2">
        <Button variant="outline" size="sm" className="w-full" onClick={onNewGroup}>
          New group
        </Button>
        <GroupList
          groups={groups ?? []}
          selectedId={selection.group ?? null}
          onSelect={(group) => select({ group: group.id, channel: undefined, tab: "groups" })}
        />
      </TabsContent>
    </Tabs>
  );
}
