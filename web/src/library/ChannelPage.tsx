import { useState, type FormEvent } from "react";
import { ExternalLink } from "lucide-react";
import { api, type Channel, type Group, type Scope, type Stage } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useChanges } from "@/lib/changes";
import { StageRule } from "@/syncs/StageRule";
import { ChannelFiltersDialog, filtersSummary } from "./ChannelFiltersDialog";
import { VideosTable } from "./VideosTable";
import { whenLabel } from "./ChannelList";

// The Channel record carries only these three counts; the rest of the pipeline is a Sync's business.
function channelCounts(channel: Channel): Record<Stage, number> {
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
  refresh,
  onNewChat,
  onRemoved,
}: {
  channel: Channel;
  groups: Group[];
  refresh: () => Promise<void>;
  onNewChat: (scope: Scope) => void;
  onRemoved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const { act, busy } = useChanges(refresh, setError);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [videosOpen, setVideosOpen] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);

  const memberOf = groups.filter((group) => group.channels.some((c) => c.id === channel.id));
  const filters = filtersSummary(channel.filters);

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (renaming !== null && (await act(() => api.renameChannel(channel.id, renaming)))) setRenaming(null);
  }

  const newChat = (
    <Button size="sm" disabled={!channel.indexed} onClick={() => onNewChat({ kind: "channel", id: channel.id })}>
      New chat
    </Button>
  );

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
        {channel.indexed ? (
          newChat
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <span tabIndex={0}>{newChat}</span>
            </TooltipTrigger>
            <TooltipContent>Not indexed, so it can't answer</TooltipContent>
          </Tooltip>
        )}
      </div>

      <fieldset disabled={busy} className="min-w-0 space-y-5">
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium">Indexing</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {filters === "" ? "All videos" : filters} · last synced {whenLabel(channel.last_synced_at)}
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
            <StageRule counts={channelCounts(channel)} detailed />
          </div>
        </section>

        {videosOpen && (
          <section className="rounded-lg border bg-card p-4">
            <VideosTable channelId={channel.id} />
          </section>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {renaming === null ? (
            <Button size="sm" variant="ghost" onClick={() => setRenaming(channel.name)}>
              Rename
            </Button>
          ) : (
            <form onSubmit={rename} className="flex flex-wrap items-center gap-2">
              <Input
                className="w-56"
                value={renaming}
                onChange={(e) => setRenaming(e.target.value)}
                aria-label="Channel name"
              />
              <Button size="sm" type="submit" disabled={renaming.trim() === ""}>
                Save
              </Button>
              <Button size="sm" variant="ghost" type="button" onClick={() => setRenaming(null)}>
                Cancel
              </Button>
            </form>
          )}
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

      {/* Keyed on the saved filters so reopening the dialog shows what is stored, not what was typed before. */}
      <ChannelFiltersDialog
        key={JSON.stringify(channel.filters)}
        channel={channel}
        act={act}
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
      />

      <Dialog open={removeOpen} onOpenChange={setRemoveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove channel</DialogTitle>
          </DialogHeader>
          <p className="text-sm">
            Remove {channel.name}, everything ingested from it, and its group memberships? Its chats stay readable.
          </p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRemoveOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={async () => {
                if (await act(() => api.deleteChannel(channel.id))) {
                  setRemoveOpen(false);
                  onRemoved();
                }
              }}
            >
              Remove channel
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
