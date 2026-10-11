import { useState } from "react";
import type { Selection } from "@/lib/url-state";
import { AddChannelDialog } from "./AddChannelDialog";
import { AddPlaylistDialog } from "./AddPlaylistDialog";
import { NewGroupDialog } from "./NewGroupDialog";

// The list column is also rendered inside the Sheet, so the dialogs it opens are held here and mounted once;
// two copies would fight over the same state and open twice.
export function useLibraryDialogs({
  select,
  reloadChannels,
  reloadGroups,
  reloadPlaylists,
}: {
  select: (selection: Selection) => void;
  reloadChannels: () => Promise<void>;
  reloadGroups: () => Promise<void>;
  reloadPlaylists: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [creating, setCreating] = useState(false);
  const [addingPlaylist, setAddingPlaylist] = useState(false);

  return {
    addChannel: () => setAdding(true),
    newGroup: () => setCreating(true),
    addPlaylist: () => setAddingPlaylist(true),
    dialogs: (
      <>
        <AddChannelDialog
          open={adding}
          onOpenChange={setAdding}
          onAdded={(channel) => {
            void reloadChannels();
            select({ channel: channel.id, group: undefined, playlist: undefined, tab: "channels" });
          }}
        />
        <NewGroupDialog
          open={creating}
          onOpenChange={setCreating}
          onCreated={(group) => {
            void reloadGroups();
            select({ group: group.id, channel: undefined, playlist: undefined, tab: "groups" });
          }}
        />
        <AddPlaylistDialog
          open={addingPlaylist}
          onOpenChange={setAddingPlaylist}
          onAdded={(playlist) => {
            void reloadPlaylists();
            select({ playlist: playlist.id, channel: undefined, group: undefined, tab: "playlists" });
          }}
        />
      </>
    ),
  };
}
