import type { Playlist, Sync } from "@/lib/api";
import { AvatarStack } from "@/components/Avatar";
import { formatWhen, plural } from "@/lib/format";
import { playlistSync, syncCounts } from "@/lib/sync-status";
import { ListRow } from "@/shell/ListRow";
import { StageRule } from "@/syncs/StageRule";

function playlistMeta(playlist: Playlist, running: Sync | null): string {
  const videos = plural(playlist.indexed_videos, "video");
  if (running !== null) return `${videos} · ${syncCounts(running)}`;
  return playlist.last_synced_at === null
    ? `${videos} · never synced`
    : `${videos} · synced ${formatWhen(playlist.last_synced_at)}`;
}

export function PlaylistList({
  playlists,
  syncs,
  selectedId,
  onSelect,
}: {
  playlists: Playlist[];
  syncs: Sync[] | null;
  selectedId: number | null;
  onSelect: (playlist: Playlist) => void;
}) {
  if (playlists.length === 0) {
    return <p className="px-2 py-3 text-xs text-muted-foreground">No playlists yet</p>;
  }
  return (
    <ul className="space-y-0.5">
      {playlists.map((playlist) => {
        const running = playlistSync(syncs, playlist.id);
        return (
          <li key={playlist.id}>
            <ListRow selected={playlist.id === selectedId} onClick={() => onSelect(playlist)}>
              <AvatarStack
                members={playlist.creators.map((c) => ({ name: c.name, src: c.avatar_url }))}
                shape="square"
                size="sm"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{playlist.name}</span>
                <span className="block truncate text-xs text-muted-foreground">{playlistMeta(playlist, running)}</span>
                {running !== null && (
                  <span className="mt-1 block">
                    <StageRule counts={running.stage_counts} detailed={false} />
                  </span>
                )}
              </span>
            </ListRow>
          </li>
        );
      })}
    </ul>
  );
}
