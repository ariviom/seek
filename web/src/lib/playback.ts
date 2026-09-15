import { useCallback, useRef, useState, type MouseEvent } from "react";
import type { Citation } from "@/lib/api";

// What the player needs of a Citation. A search result at a second is one too.
export type Playable = Pick<
  Citation,
  "youtube_video_id" | "seconds" | "video_title" | "channel_name" | "published_on" | "url"
>;
// `opening` counts plays, so playing the same moment again remounts the embed and restarts it.
export type Playback = { playable: Playable; opening: number };

export function playableKey(playable: Playable): string {
  return `${playable.youtube_video_id}@${playable.seconds}`;
}

// For a Citation link: a plain click plays it here, a modified click still opens YouTube.
export function playOnPlainClick(event: MouseEvent, play: () => void) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  play();
}

// One playback for the whole page: in the inspector's card, or large in the lightbox. With the inspector hidden there
// is no card, so playing opens the lightbox and closing it stops the video.
export function usePlayback(inspectorOpen: boolean) {
  const [playback, setPlayback] = useState<Playback | null>(null);
  const [large, setLarge] = useState(false);
  const openings = useRef(0);

  const close = useCallback(() => {
    setPlayback(null);
    setLarge(false);
  }, []);

  return {
    playback,
    large,
    playingKey: playback === null ? null : playableKey(playback.playable),
    play: useCallback(
      (playable: Playable) => {
        setPlayback({ playable, opening: ++openings.current });
        if (!inspectorOpen) setLarge(true);
      },
      [inspectorOpen],
    ),
    showLarge: useCallback(() => setLarge(true), []),
    closeLarge: useCallback(() => (inspectorOpen ? setLarge(false) : close()), [inspectorOpen, close]),
    close,
  };
}

export type PlaybackControls = ReturnType<typeof usePlayback>;
