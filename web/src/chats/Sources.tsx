import { Play } from "lucide-react";
import type { Citation } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { formatDuration } from "@/lib/format";
import { playableKey } from "@/lib/playback";
import { cn } from "@/lib/utils";

// Every Citation of the chat once, grouped by Channel, each group and its rows in first-cited order.
export function sourcesOf(citations: Citation[]): { key: string; channelName: string; citations: Citation[] }[] {
  const groups = new Map<string, { key: string; channelName: string; citations: Citation[] }>();
  const seen = new Set<string>();
  for (const citation of citations) {
    const key = playableKey(citation);
    if (seen.has(key)) continue;
    seen.add(key);
    // A Citation keeps its Channel's name after the Channel is removed, when its id is gone.
    const channelKey = citation.channel_id === null ? `name:${citation.channel_name}` : `id:${citation.channel_id}`;
    const group = groups.get(channelKey) ?? { key: channelKey, channelName: citation.channel_name, citations: [] };
    group.citations.push(citation);
    groups.set(channelKey, group);
  }
  return [...groups.values()];
}

export function Sources({
  citations,
  playingKey,
  onPlay,
}: {
  citations: Citation[];
  playingKey: string | null;
  onPlay: (citation: Citation) => void;
}) {
  const groups = sourcesOf(citations);
  if (groups.length === 0) {
    return <p className="px-1 pt-3 text-xs text-muted-foreground">Sources an answer cites are listed here.</p>;
  }
  return (
    <div className="mt-2 space-y-2">
      {groups.map((group) => (
        <section key={group.key} aria-label={group.channelName}>
          <div className="flex items-center gap-2 px-1 pt-2 pb-1">
            <Avatar name={group.channelName} size="xs" />
            <h3 className="truncate text-xs font-medium">{group.channelName}</h3>
          </div>
          <ul>
            {group.citations.map((citation) => {
              const key = playableKey(citation);
              return (
                <li key={key}>
                  <button
                    type="button"
                    aria-current={key === playingKey ? "true" : undefined}
                    onClick={() => onPlay(citation)}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/50",
                      key === playingKey && "bg-accent",
                    )}
                  >
                    <Play className="mt-1 size-3 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0">
                      <span className="block truncate text-sm">{citation.video_title}</span>
                      <span className="block text-xs text-muted-foreground tabular-nums">
                        {citation.published_on !== null && `${citation.published_on} · `}
                        {formatDuration(citation.seconds)}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
