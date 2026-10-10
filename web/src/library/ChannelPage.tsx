import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { api, type Channel, type CheckHours, type Group, type Scope, type Stage, type Sync } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useChanges } from "@/lib/changes";
import { formatWhen } from "@/lib/format";
import { channelSync, syncProgress, useNow } from "@/lib/sync-status";
import { StageRule } from "@/syncs/StageRule";
import { ChannelFiltersDialog, filtersSummary } from "./ChannelFiltersDialog";
import { RenameForm } from "./RenameForm";
import { VideosTable } from "./VideosTable";

// The Channel record carries only these three counts; the rest of the pipeline is a Sync's business, so a Channel
// mid-sync is shown its running Sync's counts, else its newest Sync's.
function channelCounts(channel: Channel, syncs: Sync[] | null): Record<Stage, number> {
  const latest = channelSync(syncs, channel.id) ?? syncs?.find((sync) => sync.channel_id === channel.id) ?? null;
  if (latest !== null) return latest.stage_counts;
  return {
    discovered: 0,
    transcript_fetched: 0,
    segmented: 0,
    embedded: 0,
    done: channel.indexed_videos,
    failed: channel.failed_videos,
    excluded: channel.excluded_videos,
  };
}

const checkLabels: Record<string, string> = { "6": "Every 6 hours", "24": "Daily", "168": "Weekly", off: "Off" };

// The server checks again once the latest Sync was queued longer ago than the interval; the list holds the newest
// Syncs, and a Channel whose latest has dropped off it is judged by when it last synced.
function nextCheck(channel: Channel, syncs: Sync[] | null, now: number): string | null {
  if (!channel.indexed) return "Paused channels aren’t checked.";
  if (channel.check_every_hours === null) return null;
  const since = syncs?.find((sync) => sync.channel_id === channel.id)?.queued_at ?? channel.last_synced_at;
  const due = since === null ? now : new Date(since).getTime() + channel.check_every_hours * 3_600_000;
  return due <= now ? "Next check soon." : `Next check around ${formatWhen(new Date(due).toISOString())}.`;
}

export function ChannelPage({
  channel,
  groups,
  syncs,
  refresh,
  onNewChat,
  onOpenSync,
  onRemoved,
}: {
  channel: Channel;
  groups: Group[];
  syncs: Sync[] | null;
  refresh: () => Promise<void>;
  onNewChat: (scope: Scope) => void;
  onOpenSync: (syncId: number) => void;
  onRemoved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const { act, busy } = useChanges(refresh, setError);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [videosOpen, setVideosOpen] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);

  const memberOf = groups.filter((group) => group.channels.some((c) => c.id === channel.id));
  const filters = filtersSummary(channel.filters);
  const running = channelSync(syncs, channel.id);
  const now = useNow(running === null ? 0 : 10);
  const checkNote = nextCheck(channel, syncs, now);

  return (
    <div className="space-y-5">
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex items-start gap-3">
        <Avatar name={channel.name} src={channel.avatar_url} size="lg" />
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold tracking-tight">
            <a
              className="inline-flex items-center gap-1.5 underline-offset-2 hover:underline"
              href={`https://www.youtube.com/channel/${channel.youtube_channel_id}`}
              target="_blank"
              rel="noreferrer"
            >
              {channel.name}
              <ExternalLink className="size-4 text-muted-foreground" aria-hidden />
            </a>
          </h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {memberOf.length === 0 ? (
              <span className="text-xs text-muted-foreground">In no group yet</span>
            ) : (
              memberOf.map((group) => (
                <Badge key={group.id} variant="secondary">
                  {group.name}
                </Badge>
              ))
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!channel.indexed && <Badge variant="outline">Paused</Badge>}
          <Button size="sm" disabled={!channel.indexed} onClick={() => onNewChat({ kind: "channel", id: channel.id })}>
            New chat
          </Button>
        </div>
      </div>

      <fieldset disabled={busy} className="min-w-0 space-y-5">
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium">Videos</h2>
          {running === null ? (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {filters === "" ? "All videos" : filters} · last synced {formatWhen(channel.last_synced_at)}
            </p>
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
              onClick={() => void act(() => api.startSync(channel.id))}
            >
              {running === null ? "Sync now" : "Syncing…"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => void act(() => api.retryFailed(channel.id))}>
              Retry failed videos
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setFiltersOpen(true)}>
              Filters
            </Button>
            <Button size="sm" variant="ghost" aria-expanded={videosOpen} onClick={() => setVideosOpen(!videosOpen)}>
              Videos
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span id="channel-checks" className="text-xs text-muted-foreground">
              Check for new videos
            </span>
            <Select
              value={channel.check_every_hours === null ? "off" : String(channel.check_every_hours)}
              onValueChange={(value) =>
                void act(() =>
                  api.setChannelChecks(channel.id, value === "off" ? null : (Number(value) as CheckHours)),
                )
              }
            >
              <SelectTrigger size="sm" className="w-36" aria-labelledby="channel-checks">
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
            <StageRule counts={channelCounts(channel, syncs)} detailed />
          </div>
        </section>

        {videosOpen && (
          <section className="rounded-lg border bg-card p-4">
            <VideosTable channelId={channel.id} />
          </section>
        )}

        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <RenameForm
              label="Channel name"
              name={channel.name}
              onRename={(name) => act(() => api.renameChannel(channel.id, name))}
            />
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void act(() => api.setChannelIndexed(channel.id, !channel.indexed))}
            >
              {channel.indexed ? "Pause channel" : "Resume channel"}
            </Button>
            <Button size="sm" variant="destructive" className="ml-auto" onClick={() => setRemoveOpen(true)}>
              Remove channel
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            A paused channel isn’t synced and doesn’t answer; what’s ingested stays.
          </p>
        </div>
      </fieldset>

      <ChannelFiltersDialog channel={channel} act={act} open={filtersOpen} onOpenChange={setFiltersOpen} />

      <ConfirmDialog
        title="Remove channel"
        actionLabel="Remove channel"
        open={removeOpen}
        busy={busy}
        onOpenChange={setRemoveOpen}
        onConfirm={async () => {
          if (await act(() => api.deleteChannel(channel.id))) {
            setRemoveOpen(false);
            onRemoved();
          }
        }}
      >
        Remove {channel.name}, everything ingested from it, and its group memberships? Its chats stay readable.
      </ConfirmDialog>
    </div>
  );
}
