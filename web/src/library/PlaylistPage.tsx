import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { api, type CheckHours, type Playlist, type Scope, type Stage, type Sync } from "@/lib/api";
import { AvatarStack } from "@/components/Avatar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useChanges } from "@/lib/changes";
import { checkLabels, formatWhen } from "@/lib/format";
import { playlistSync, syncProgress, useNow } from "@/lib/sync-status";
import { StageRule } from "@/syncs/StageRule";
import { RenameForm } from "./RenameForm";
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

// The server says when the next check is; one never synced waits for its first Sync, which the user starts.
function nextCheck(playlist: Playlist, now: number): string | null {
  if (!playlist.indexed) return "Paused playlists aren’t checked.";
  if (playlist.check_every_hours === null) return null;
  if (playlist.next_check_at === null) return "Checks start after its first sync.";
  return new Date(playlist.next_check_at).getTime() <= now
    ? "Next check soon."
    : `Next check around ${formatWhen(playlist.next_check_at)}.`;
}

export function PlaylistPage({
  playlist,
  syncs,
  refresh,
  onNewChat,
  onOpenSync,
  onRemoved,
}: {
  playlist: Playlist;
  syncs: Sync[] | null;
  refresh: () => Promise<void>;
  onNewChat: (scope: Scope) => void;
  onOpenSync: (syncId: number) => void;
  onRemoved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const { act, busy } = useChanges(refresh, setError);
  const [removeOpen, setRemoveOpen] = useState(false);

  const running = playlistSync(syncs, playlist.id);
  const now = useNow(running === null ? 0 : 10);
  const checkNote = nextCheck(playlist, now);

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
        <div className="flex items-center gap-2">
          {!playlist.indexed && <Badge variant="outline">Paused</Badge>}
          <Button
            size="sm"
            disabled={!playlist.indexed || playlist.creators.length === 0}
            onClick={() => onNewChat({ kind: "playlist", id: playlist.id })}
          >
            New chat
          </Button>
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
          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span id="playlist-checks" className="text-xs text-muted-foreground">
              Check for changes
            </span>
            <Select
              value={playlist.check_every_hours === null ? "off" : String(playlist.check_every_hours)}
              onValueChange={(value) =>
                void act(() =>
                  api.setPlaylistChecks(playlist.id, value === "off" ? null : (Number(value) as CheckHours)),
                )
              }
            >
              <SelectTrigger size="sm" className="w-36" aria-labelledby="playlist-checks">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(checkLabels).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {checkNote !== null && <span className="text-xs text-muted-foreground">{checkNote}</span>}
          </div>
          <div className="mt-4">
            <StageRule counts={playlistCounts(playlist, syncs)} detailed />
          </div>
          <div className="mt-4">
            <VideosTable source={{ kind: "playlist", id: playlist.id }} />
          </div>
        </section>

        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <RenameForm
              label="Playlist name"
              name={playlist.name}
              onRename={(name) => act(() => api.renamePlaylist(playlist.id, name))}
            />
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void act(() => api.setPlaylistIndexed(playlist.id, !playlist.indexed))}
            >
              {playlist.indexed ? "Pause playlist" : "Resume playlist"}
            </Button>
            <Button size="sm" variant="destructive" className="ml-auto" onClick={() => setRemoveOpen(true)}>
              Remove playlist
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            A paused playlist isn’t synced and doesn’t answer; what’s ingested stays.
          </p>
        </div>
      </fieldset>

      <ConfirmDialog
        title="Remove playlist"
        actionLabel="Remove playlist"
        open={removeOpen}
        busy={busy}
        onOpenChange={setRemoveOpen}
        onConfirm={async () => {
          if (await act(() => api.deletePlaylist(playlist.id))) {
            setRemoveOpen(false);
            onRemoved();
          }
        }}
      >
        Remove {playlist.name}? Its videos go too, except those a channel in the Library or another playlist
        includes. Its chats stay readable.
      </ConfirmDialog>
    </div>
  );
}
