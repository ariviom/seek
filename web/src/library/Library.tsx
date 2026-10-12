import { useState } from "react";
import type { Selection } from "@/lib/url-state";
import { AddChannelDialog } from "./AddChannelDialog";
import { AddPlaylistDialog } from "./AddPlaylistDialog";
import type { ImportHandlers } from "./ImportBundle";
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
  const reloadEntries = () => {
    void reloadChannels();
    void reloadPlaylists();
  };
  // Either Add dialog imports either kind of Bundle, so both answer an import the same way: what arrived is
  // selected on the tab of its kind.
  const imports: ImportHandlers = {
    onImported: (report) => {
      reloadEntries();
      select(
        report.kind === "channel"
          ? { channel: report.id, group: undefined, playlist: undefined, tab: "channels" }
          : { playlist: report.id, channel: undefined, group: undefined, tab: "playlists" },
      );
    },
    onRefused: reloadEntries,
  };

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
          imports={imports}
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
          imports={imports}
        />
      </>
    ),
  };
}
