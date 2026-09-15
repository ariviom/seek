import { useEffect, useRef } from "react";
import type { Expansion as ExpansionShape } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

// The Transcript either side of a result, scrolled to where the Segment starts; the Segment's lines stand out and the
// matched line is marked. Each line's time plays the Video from there.
export function Expansion({
  expansion,
  matchedSeconds,
  onPlay,
}: {
  expansion: ExpansionShape;
  matchedSeconds: number;
  onPlay: (seconds: number) => void;
}) {
  const firstInSegment = useRef<HTMLLIElement>(null);
  const list = useRef<HTMLOListElement>(null);
  const firstIndex = expansion.cues.findIndex((cue) => cue.start_seconds >= expansion.start_seconds);
  // The last cue starting at or before the matched second.
  const matchedIndex = expansion.cues.reduce((found, cue, index) => (cue.start_seconds <= matchedSeconds ? index : found), -1);

  useEffect(() => {
    // The list is positioned, so a line's offsetTop is measured within it.
    if (list.current && firstInSegment.current) list.current.scrollTop = firstInSegment.current.offsetTop;
  }, []);

  return (
    <ol
      ref={list}
      className="relative mt-2 max-h-72 space-y-0.5 overflow-y-auto rounded-md border bg-muted/30 py-2 pr-2 pl-3"
      aria-label={`Transcript around this moment in ${expansion.video_title}`}
    >
      {expansion.cues.map((cue, index) => {
        const start = Math.floor(cue.start_seconds);
        const inSegment = cue.start_seconds >= expansion.start_seconds && cue.start_seconds < expansion.end_seconds;
        const matched = index === matchedIndex;
        return (
          <li
            key={index}
            ref={index === firstIndex ? firstInSegment : undefined}
            aria-current={matched ? "true" : undefined}
            className={cn(
              "grid grid-cols-[3.25rem_1fr] gap-2 rounded-sm text-sm leading-6",
              inSegment ? "text-foreground" : "text-muted-foreground",
              matched && "bg-amber-400/15",
            )}
          >
            <button
              type="button"
              className="rounded-sm text-left text-xs leading-6 text-muted-foreground tabular-nums outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
              onClick={() => onPlay(start)}
              aria-label={`Play at ${formatDuration(start)}`}
            >
              {formatDuration(start)}
            </button>
            <span>{cue.text}</span>
          </li>
        );
      })}
    </ol>
  );
}
