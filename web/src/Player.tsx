import { useEffect, useRef, useState, type MouseEvent } from "react";
import type { Citation } from "./api";
import { formatDuration, quietButtonClass } from "./ui";

// What the player needs of a Citation. A search result at a second is one too.
export type PlayerCitation = Pick<Citation, "youtube_video_id" | "seconds" | "video_title" | "mentor_name">;

// The open player, if any, and where it was opened (e.g. which search result). `opening` counts plays, so playing the
// same Citation again restarts it.
export function usePlayer<Where>() {
  const [playing, setPlaying] = useState<{ where: Where; citation: PlayerCitation; opening: number } | null>(null);
  const openings = useRef(0);
  return {
    playing,
    play: (where: Where, citation: PlayerCitation) => setPlaying({ where, citation, opening: ++openings.current }),
    close: () => setPlaying(null),
  };
}

// For a Citation link: a plain click plays it here, a modified click still opens YouTube.
export function playOnPlainClick(event: MouseEvent, play: () => void) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  play();
}

// A Citation's Video embedded at its second. The embed carries YouTube's own link out, including when the uploader
// has disabled embedding.
export function CitationPlayer({
  citation,
  opening,
  onClose,
}: {
  citation: PlayerCitation;
  opening: number;
  onClose: () => void;
}) {
  const at = formatDuration(citation.seconds);
  const id = encodeURIComponent(citation.youtube_video_id);
  const figure = useRef<HTMLElement>(null);

  // The player may open out of view of the link that opened it.
  useEffect(() => {
    figure.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [opening]);

  return (
    <figure ref={figure} className="mt-3">
      <div className="aspect-video overflow-hidden rounded-md bg-ink">
        <iframe
          key={opening}
          className="size-full"
          src={`https://www.youtube-nocookie.com/embed/${id}?start=${citation.seconds}&autoplay=1`}
          title={`${citation.video_title} at ${at}`}
          allow="autoplay; encrypted-media; fullscreen; picture-in-picture"
          allowFullScreen
          // The browser default, stated because YouTube refuses to play embeds that send no referrer.
          referrerPolicy="strict-origin-when-cross-origin"
        />
      </div>
      <figcaption className="mt-1 flex items-baseline justify-between gap-3 text-[13px] text-pencil">
        <span className="min-w-0 truncate">
          {citation.mentor_name} · {citation.video_title} at <span className="tabular-nums">{at}</span>
        </span>
        <button className={quietButtonClass} type="button" onClick={onClose}>
          Close player
        </button>
      </figcaption>
    </figure>
  );
}
