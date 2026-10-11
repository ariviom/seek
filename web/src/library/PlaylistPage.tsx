import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { api, type Playlist, type Stage, type Sync } from "@/lib/api";
import { AvatarStack } from "@/components/Avatar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useChanges } from "@/lib/changes";
import { formatWhen } from "@/lib/format";
import { playlistSync, syncProgress, useNow } from "@/lib/sync-status";
import { StageRule } from "@/syncs/StageRule";
import { VideosTable } from "./VideosTable";

// As for a Channel: mid-sync the running Sync's counts, else the newest Sync's, else the record's own three.
function playlistCounts(playlist: Playlist, syncs: Sync[] | null): Record<Stage, number> {
  const latest =
    playlistSync(syncs, playlist.id) ?? syncs?.find((sync) => sync.playlist_id === playlist.id) ?? null;
  if (latest !== null) return latest.stage_counts;
  return {
    discovered: 0,
    transcript_fetched: 0,
    segmented: 0,
    embedded: 0,
    done: playlist.indexed_videos,
    failed: playlist.failed_videos,
    excluded: playlist.excluded_videos,
  };
}

export function PlaylistPage({
  playlist,
  syncs,
  refresh,
  onOpenSync,
}: {
  playlist: Playlist;
  syncs: Sync[] | null;
  refresh: () => Promise<void>;
  onOpenSync: (syncId: number) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const { act, busy } = useChanges(refresh, setError);

  const running = playlistSync(syncs, playlist.id);
  const now = useNow(running === null ? 0 : 10);

  return (
    <div className="space-y-5">
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex items-start gap-3">
        <AvatarStack
          members={playlist.creators.map((c) => ({ name: c.name, src: c.avatar_url }))}
          shape="square"
          size="lg"
          ringClassName="ring-background"
        />
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold tracking-tight">
            <a
              className="inline-flex items-center gap-1.5 underline-offset-2 hover:underline"
              href={`https://www.youtube.com/playlist?list=${playlist.youtube_playlist_id}`}
              target="_blank"
              rel="noreferrer"
            >
              {playlist.name}
              <ExternalLink className="size-4 text-muted-foreground" aria-hidden />
            </a>
          </h1>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {playlist.creators.length === 0
              ? "No creators yet"
              : `Videos by ${playlist.creators.map((c) => c.name).join(", ")}`}
          </p>
        </div>
      </div>

      <fieldset disabled={busy} className="min-w-0 space-y-5">
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium">Videos</h2>
          {running === null ? (
            <p className="mt-0.5 text-xs text-muted-foreground">last synced {formatWhen(playlist.last_synced_at)}</p>
          ) : (
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              <button type="button" className="underline-offset-2 hover:underline" onClick={() => onOpenSync(running.id)}>
                {syncProgress(running, now).label}
              </button>
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={running !== null}
              onClick={() => void act(() => api.startPlaylistSync(playlist.id))}
            >
              {running === null ? "Sync now" : "Syncing…"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => void act(() => api.retryPlaylistFailed(playlist.id))}>
              Retry failed videos
            </Button>
          </div>
          <div className="mt-4">
            <StageRule counts={playlistCounts(playlist, syncs)} detailed />
          </div>
          <div className="mt-4">
            <VideosTable source={{ kind: "playlist", id: playlist.id }} />
          </div>
        </section>
      </fieldset>
    </div>
  );
}
