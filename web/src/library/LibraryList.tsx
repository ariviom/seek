import type { Channel, Group, Playlist, Sync } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { LibraryTab, Selection } from "@/lib/url-state";
import { ChannelList } from "./ChannelList";
import { GroupList } from "./GroupList";
import { PlaylistList } from "./PlaylistList";

export function LibraryList({
  channels,
  groups,
  playlists,
  syncs,
  selection,
  select,
  onAddChannel,
  onNewGroup,
  onAddPlaylist,
}: {
  channels: Channel[] | null;
  groups: Group[] | null;
  playlists: Playlist[] | null;
  syncs: Sync[] | null;
  selection: Selection;
  select: (selection: Selection) => void;
  onAddChannel: () => void;
  onNewGroup: () => void;
  onAddPlaylist: () => void;
}) {
  const tab = selection.tab ?? "channels";

  return (
    <Tabs value={tab} onValueChange={(value) => select({ tab: value as LibraryTab })}>
      <TabsList className="w-full">
        <TabsTrigger value="channels">Channels</TabsTrigger>
        <TabsTrigger value="groups">Groups</TabsTrigger>
        <TabsTrigger value="playlists">Playlists</TabsTrigger>
      </TabsList>
      <TabsContent value="channels" className="mt-2 space-y-2">
        <Button variant="outline" size="sm" className="w-full" onClick={onAddChannel}>
          Add channel
        </Button>
        <ChannelList
          channels={channels ?? []}
          syncs={syncs}
          selectedId={selection.channel ?? null}
          onSelect={(channel) => select({ channel: channel.id, group: undefined, playlist: undefined, tab: "channels" })}
        />
      </TabsContent>
      <TabsContent value="groups" className="mt-2 space-y-2">
        <Button variant="outline" size="sm" className="w-full" onClick={onNewGroup}>
          New group
        </Button>
        <GroupList
          groups={groups ?? []}
          selectedId={selection.group ?? null}
          onSelect={(group) => select({ group: group.id, channel: undefined, playlist: undefined, tab: "groups" })}
        />
      </TabsContent>
      <TabsContent value="playlists" className="mt-2 space-y-2">
        <Button variant="outline" size="sm" className="w-full" onClick={onAddPlaylist}>
          Add playlist
        </Button>
        <PlaylistList
          playlists={playlists ?? []}
          syncs={syncs}
          selectedId={selection.playlist ?? null}
          onSelect={(playlist) =>
            select({ playlist: playlist.id, channel: undefined, group: undefined, tab: "playlists" })
          }
        />
      </TabsContent>
    </Tabs>
  );
}
