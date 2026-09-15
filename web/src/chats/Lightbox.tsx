import { useRef } from "react";
import { ExternalLink, X } from "lucide-react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogDescription, DialogOverlay, DialogPortal, DialogTitle } from "@/components/ui/dialog";
import { formatDuration } from "@/lib/format";
import type { PlaybackControls } from "@/lib/playback";
import { YouTubeEmbed } from "./PlayerCard";

const onDark = "border-white/15 bg-transparent text-zinc-100 hover:bg-white/10 hover:text-zinc-100 dark:bg-transparent";

// The video large over a dimmed page. Radix's Dialog brings Esc, the backdrop click, and focus handling; its content
// is used directly because shadcn's DialogContent fixes a light overlay and a card surface.
export function Lightbox({ controls }: { controls: PlaybackControls }) {
  const { playback } = controls;
  const closeButton = useRef<HTMLButtonElement>(null);
  return (
    <Dialog open={controls.large && playback !== null} onOpenChange={(open) => !open && controls.closeLarge()}>
      {playback !== null && (
        <DialogPortal>
          <DialogOverlay className="bg-black/80" />
          <DialogPrimitive.Content
            // Radix would focus the first focusable element, the embed, and Esc would then go to YouTube's page.
            onOpenAutoFocus={(event) => {
              event.preventDefault();
              closeButton.current?.focus();
            }}
            className="fixed top-1/2 left-1/2 z-50 w-[min(64rem,calc(100%-3rem))] -translate-x-1/2 -translate-y-1/2 outline-none">
            <div className="aspect-video overflow-hidden rounded-xl bg-black shadow-2xl ring-1 ring-white/10">
              <YouTubeEmbed playback={playback} />
            </div>
            <div className="mt-3 flex items-center gap-3">
              <Avatar name={playback.playable.channel_name} size="sm" />
              <div className="min-w-0 flex-1">
                <DialogTitle className="truncate text-sm font-medium text-zinc-100">
                  {playback.playable.video_title}
                </DialogTitle>
                <DialogDescription className="truncate text-xs text-zinc-400 tabular-nums">
                  {[playback.playable.channel_name, playback.playable.published_on]
                    .filter((part) => part !== null)
                    .join(" · ")}{" "}
                  · from {formatDuration(playback.playable.seconds)}
                </DialogDescription>
              </div>
              <Button variant="outline" size="sm" className={onDark} asChild>
                <a href={playback.playable.url} target="_blank" rel="noreferrer">
                  <ExternalLink /> Open on YouTube
                </a>
              </Button>
              <Button
                ref={closeButton}
                variant="outline"
                size="icon-sm"
                className={onDark}
                aria-label="Close"
                onClick={controls.closeLarge}
              >
                <X />
              </Button>
            </div>
          </DialogPrimitive.Content>
        </DialogPortal>
      )}
    </Dialog>
  );
}
