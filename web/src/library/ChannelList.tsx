import type { Channel } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { cn } from "@/lib/utils";

export function whenLabel(at: string | null): string {
  if (at === null) return "never";
  return new Date(at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function channelMeta(channel: Channel): string {
  const videos = `${channel.indexed_videos} ${channel.indexed_videos === 1 ? "video" : "videos"}`;
  return channel.last_synced_at === null
    ? `${videos} · never synced`
    : `${videos} · synced ${whenLabel(channel.last_synced_at)}`;
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
          <button
            type="button"
            aria-current={channel.id === selectedId ? "true" : undefined}
            onClick={() => onSelect(channel)}
            className={cn(
              "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-sidebar-accent",
              channel.id === selectedId && "bg-sidebar-accent",
            )}
          >
            <Avatar name={channel.name} size="md" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{channel.name}</span>
              <span className="block truncate text-xs text-muted-foreground">{channelMeta(channel)}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
