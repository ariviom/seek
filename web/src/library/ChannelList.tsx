import type { Channel } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { formatWhen, plural } from "@/lib/format";
import { ListRow } from "@/shell/ListRow";

function channelMeta(channel: Channel): string {
  const videos = plural(channel.indexed_videos, "video");
  return channel.last_synced_at === null
    ? `${videos} · never synced`
    : `${videos} · synced ${formatWhen(channel.last_synced_at)}`;
}

export function ChannelList({
  channels,
  selectedId,
  onSelect,
}: {
  channels: Channel[];
  selectedId: number | null;
  onSelect: (channel: Channel) => void;
}) {
  if (channels.length === 0) {
    return <p className="px-2 py-3 text-xs text-muted-foreground">Add a channel to start</p>;
  }
  return (
    <ul className="space-y-0.5">
      {channels.map((channel) => (
        <li key={channel.id}>
          <ListRow selected={channel.id === selectedId} onClick={() => onSelect(channel)}>
            <Avatar name={channel.name} size="md" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{channel.name}</span>
              <span className="block truncate text-xs text-muted-foreground">{channelMeta(channel)}</span>
            </span>
          </ListRow>
        </li>
      ))}
    </ul>
  );
}
