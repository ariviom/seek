import type { Channel, Sync } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { formatWhen, plural } from "@/lib/format";
import { channelSync, syncCounts } from "@/lib/sync-status";
import { ListRow } from "@/shell/ListRow";
import { StageRule } from "@/syncs/StageRule";

function channelMeta(channel: Channel, running: Sync | null): string {
  const videos = plural(channel.indexed_videos, "video");
  if (running !== null) return `${videos} · ${syncCounts(running)}`;
  return channel.last_synced_at === null
    ? `${videos} · never synced`
    : `${videos} · synced ${formatWhen(channel.last_synced_at)}`;
}

export function ChannelList({
  channels,
  syncs,
  selectedId,
  onSelect,
}: {
  channels: Channel[];
  syncs: Sync[] | null;
  selectedId: number | null;
  onSelect: (channel: Channel) => void;
}) {
  if (channels.length === 0) {
    return <p className="px-2 py-3 text-xs text-muted-foreground">Add a channel to start</p>;
  }
  return (
    <ul className="space-y-0.5">
      {channels.map((channel) => {
        const running = channelSync(syncs, channel.id);
        return (
          <li key={channel.id}>
            <ListRow selected={channel.id === selectedId} onClick={() => onSelect(channel)}>
              <Avatar name={channel.name} src={channel.avatar_url} size="md" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{channel.name}</span>
                <span className="block truncate text-xs text-muted-foreground">{channelMeta(channel, running)}</span>
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
