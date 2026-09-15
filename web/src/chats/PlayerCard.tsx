import { ExternalLink, Maximize2, X } from "lucide-react";
import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { formatDuration } from "@/lib/format";
import type { Playback, PlaybackControls } from "@/lib/playback";

// A Citation's Video embedded at its second. The embed carries YouTube's own link out, including when the uploader
// has disabled embedding.
export function YouTubeEmbed({ playback }: { playback: Playback }) {
  const { playable, opening } = playback;
  const id = encodeURIComponent(playable.youtube_video_id);
  return (
    <iframe
      key={opening}
      className="size-full"
      src={`https://www.youtube-nocookie.com/embed/${id}?start=${playable.seconds}&autoplay=1`}
      title={`${playable.video_title} at ${formatDuration(playable.seconds)}`}
      allow="autoplay; encrypted-media; fullscreen; picture-in-picture"
      allowFullScreen
      // The browser default, stated because YouTube refuses to play embeds that send no referrer.
      referrerPolicy="strict-origin-when-cross-origin"
    />
  );
}

// The inspector's player. While the lightbox is open it hands over the video, so two players never run.
export function PlayerCard({ controls, empty }: { controls: PlaybackControls; empty: string }) {
  const { playback } = controls;
  if (playback === null) {
    return (
      <p className="flex aspect-video items-center justify-center rounded-lg border border-dashed px-5 text-center text-xs text-muted-foreground">
        {empty}
      </p>
    );
  }
  const { playable } = playback;
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="aspect-video bg-black">
        {controls.large ? (
          <p className="flex size-full items-center justify-center text-xs text-zinc-400">Playing large</p>
        ) : (
          <YouTubeEmbed playback={playback} />
        )}
      </div>
      <div className="flex items-center gap-1 py-1.5 pr-1 pl-2.5">
        <Avatar name={playable.channel_name} size="xs" />
        <span className="ml-1 min-w-0 flex-1">
          <span className="block truncate text-xs">{playable.video_title}</span>
          <span className="block truncate text-[11px] text-muted-foreground tabular-nums">
            {playable.channel_name} · {formatDuration(playable.seconds)}
          </span>
        </span>
        <Button variant="ghost" size="icon-sm" aria-label="Show large" title="Show large" onClick={controls.showLarge}>
          <Maximize2 />
        </Button>
        <Button variant="ghost" size="icon-sm" asChild>
          <a href={playable.url} target="_blank" rel="noreferrer" aria-label="Open on YouTube" title="Open on YouTube">
            <ExternalLink />
          </a>
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Close player" title="Close player" onClick={controls.close}>
          <X />
        </Button>
      </div>
    </div>
  );
}
