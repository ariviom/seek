import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { api, type Channel, type Group, type Scope, type Stage, type Sync } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useChanges } from "@/lib/changes";
import { formatWhen } from "@/lib/format";
import { StageRule } from "@/syncs/StageRule";
import { ChannelFiltersDialog, filtersSummary } from "./ChannelFiltersDialog";
import { RenameForm } from "./RenameForm";
import { VideosTable } from "./VideosTable";

// The Channel record carries only these three counts; the rest of the pipeline is a Sync's business, so a Channel
// mid-sync is shown its newest Sync's counts instead.
function channelCounts(channel: Channel, syncs: Sync[] | null): Record<Stage, number> {
  const latest = syncs?.find((sync) => sync.channel_id === channel.id);
  if (latest !== undefined) return latest.stage_counts;
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

export function ChannelPage({
  channel,
  groups,
  syncs,
  refresh,
  onNewChat,
  onRemoved,
}: {
  channel: Channel;
  groups: Group[];
  syncs: Sync[] | null;
  refresh: () => Promise<void>;
  onNewChat: (scope: Scope) => void;
  onRemoved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const { act, busy } = useChanges(refresh, setError);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [videosOpen, setVideosOpen] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);

  const memberOf = groups.filter((group) => group.channels.some((c) => c.id === channel.id));
  const filters = filtersSummary(channel.filters);

  return (
    <div className="space-y-5">
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex items-start gap-3">
        <Avatar name={channel.name} size="lg" />
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
          {!channel.indexed && <span className="text-xs text-muted-foreground">Not indexed, so it can’t answer</span>}
          <Button size="sm" disabled={!channel.indexed} onClick={() => onNewChat({ kind: "channel", id: channel.id })}>
            New chat
          </Button>
        </div>
      </div>

      <fieldset disabled={busy} className="min-w-0 space-y-5">
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium">Indexing</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {filters === "" ? "All videos" : filters} · last synced {formatWhen(channel.last_synced_at)}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => void act(() => api.startSync(channel.id))}>
              Sync now
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
          <div className="mt-4">
            <StageRule counts={channelCounts(channel, syncs)} detailed />
          </div>
        </section>

        {videosOpen && (
          <section className="rounded-lg border bg-card p-4">
            <VideosTable channelId={channel.id} />
          </section>
        )}

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
            {channel.indexed ? "Stop indexing" : "Resume indexing"}
          </Button>
          <Button size="sm" variant="destructive" className="ml-auto" onClick={() => setRemoveOpen(true)}>
            Remove channel
          </Button>
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
