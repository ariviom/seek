import { useState, type FormEvent } from "react";
import { api, type Channel, type ChannelFilters } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { Act } from "@/lib/changes";

const noFilters: ChannelFilters = {
  published_after: null,
  published_before: null,
  playlist_id: null,
  most_recent: null,
};

export function filtersSummary(filters: ChannelFilters): string {
  return [
    filters.published_after && `published from ${filters.published_after}`,
    filters.published_before && `published until ${filters.published_before}`,
    filters.playlist_id && `playlist ${filters.playlist_id}`,
    filters.most_recent !== null && `the ${filters.most_recent} most recent`,
  ]
    .filter(Boolean)
    .join(", ");
}

export function ChannelFiltersDialog({
  channel,
  act,
  open,
  onOpenChange,
}: {
  channel: Channel;
  act: Act;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [after, setAfter] = useState(channel.filters.published_after ?? "");
  const [before, setBefore] = useState(channel.filters.published_before ?? "");
  const [playlist, setPlaylist] = useState(channel.filters.playlist_id ?? "");
  const [mostRecent, setMostRecent] = useState(channel.filters.most_recent?.toString() ?? "");

  async function save(filters: ChannelFilters) {
    if (await act(() => api.setChannelFilters(channel.id, filters))) onOpenChange(false);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void save({
      published_after: after || null,
      published_before: before || null,
      playlist_id: playlist.trim() || null,
      most_recent: mostRecent ? Number(mostRecent) : null,
    });
  }

  const label = "grid gap-1.5 text-sm text-muted-foreground";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Filters</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit}>
          <p className="text-xs text-muted-foreground">
            Only videos matching every filter are ingested. Leave a field empty to skip it.
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className={label}>
              Published on or after
              <Input type="date" value={after} onChange={(e) => setAfter(e.target.value)} />
            </label>
            <label className={label}>
              Published on or before
              <Input type="date" value={before} onChange={(e) => setBefore(e.target.value)} />
            </label>
            <label className={label}>
              In playlist
              <Input
                placeholder="Playlist URL or PL… id"
                value={playlist}
                onChange={(e) => setPlaylist(e.target.value)}
              />
            </label>
            <label className={label}>
              Most recent videos
              <Input
                type="number"
                min={1}
                step={1}
                placeholder="All"
                value={mostRecent}
                onChange={(e) => setMostRecent(e.target.value)}
              />
            </label>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button type="submit">Save</Button>
            <Button type="button" variant="ghost" onClick={() => void save(noFilters)}>
              Clear
            </Button>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <span className="text-xs text-muted-foreground">The next Sync applies them.</span>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
