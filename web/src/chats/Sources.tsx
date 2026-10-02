import { Play } from "lucide-react";
import type { Citation, Moment } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { FrameStrip, momentKey, sourcesFrames, useFrames } from "@/components/Frames";
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

// What one Video's strip asks for: three frames from the first moment of it this chat cited.
function momentOf(citation: Citation): Moment {
  return { video_id: citation.video_id, seconds: citation.seconds, count: sourcesFrames };
}

// The first moment cited of each Video, in the order the Videos were first cited: what a strip shows.
function citedVideos(citations: Citation[]): Citation[] {
  const first = new Map<number, Citation>();
  for (const citation of citations) if (!first.has(citation.video_id)) first.set(citation.video_id, citation);
  return [...first.values()];
}

export function Sources({
  citations,
  thumbnails,
  playingKey,
  onPlay,
}: {
  citations: Citation[];
  // Whether each Channel group carries frames of what it cites; off, every row carries its Video's title again.
  thumbnails: boolean;
  playingKey: string | null;
  onPlay: (citation: Citation) => void;
}) {
  const groups = sourcesOf(citations);
  const cited = citedVideos(groups.flatMap((group) => group.citations));
  const frames = useFrames(cited.map(momentOf), thumbnails);
  if (groups.length === 0) {
    return <p className="px-1 pt-3 text-xs text-muted-foreground">Sources an answer cites are listed here.</p>;
  }
  return (
    <div className="mt-2 space-y-2">
      {groups.map((group) => {
        const strips = citedVideos(group.citations).filter((citation) => frames.frames.has(momentKey(momentOf(citation))));
        return (
        <section key={group.key} aria-label={group.channelName}>
          <div className="flex items-center gap-2 px-1 pt-2 pb-1">
            <Avatar name={group.channelName} size="xs" />
            <h3 className="truncate text-xs font-medium">{group.channelName}</h3>
          </div>
          {/* One strip per cited Video of this Channel, each frame playing that Video's cited moment. Several
              scroll sideways rather than squeezing the frames narrower than they read at. */}
          {strips.length > 0 && (
            <div className="flex gap-2 overflow-x-auto px-1 pb-1.5">
              {strips.map((citation) => {
                const video = frames.frames.get(momentKey(momentOf(citation)));
                return (
                  video !== undefined && (
                    <FrameStrip
                      key={citation.video_id}
                      video={video}
                      title={citation.video_title}
                      onBroken={() => frames.markBroken(momentOf(citation))}
                      frameClassName="w-[74px]"
                      onActivate={() => onPlay(citation)}
                    />
                  )
                );
              })}
            </div>
          )}
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
                    {/* With the strip above carrying the Video, the moment's time leads the row instead of a
                        title the strip has already given; a naked date would leave the row unreadable. */}
                    {strips.some((strip) => strip.video_id === citation.video_id) ? (
                      <span className="min-w-0 text-xs tabular-nums">
                        <span className="font-medium">{formatDuration(citation.seconds)}</span>
                        {citation.published_on !== null && (
                          <span className="text-muted-foreground"> · {citation.published_on}</span>
                        )}
                      </span>
                    ) : (
                      <span className="min-w-0">
                        <span className="block truncate text-sm">{citation.video_title}</span>
                        <span className="block text-xs text-muted-foreground tabular-nums">
                          {citation.published_on !== null && `${citation.published_on} · `}
                          {formatDuration(citation.seconds)}
                        </span>
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
        );
      })}
    </div>
  );
}
