// Frames of the moment a result or a Citation points at, cropped out of YouTube's scrubber storyboard sheets.
//
// They are an index, not evidence: enough to recognise a moment, never enough to read what is on screen. A sheet is
// a grid of tiles, so a frame is one <img> of the whole sheet, scaled to `columns` by `rows` boxes and shifted so the
// wanted tile fills the box. An <img> rather than a background image, because a sheet whose signed URL has expired
// has to be noticed: as a background it would be an undetectable blank tile.
import { useEffect, useState } from "react";
import { api, errorText, type Frame, type Moment, type Settings, type VideoFrames } from "@/lib/api";
import { HoverCard } from "radix-ui";
import { Switch } from "@/components/ui/switch";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

// Frames per strip: a search row has the width for five, the Sources column reads as texture past three.
export const searchFrames = 5;
export const sourcesFrames = 3;
// The most moments one request may carry, as storyboards_api caps it: more are asked for in further requests, so a
// chat citing dozens of Videos loses at most the Videos of a request that failed.
const maxMoments = 60;
// One width for every peek, whatever tier the Video has. Sizing it per tier made the card jump about, and a frame
// from the 160x90 tier a quarter of Videos offer upscales soft here; that is accepted, and it claims no legibility.
const peekWidth = 320;

export type Frames = {
  // The frames each moment has, by momentKey. A moment is absent when nothing stored can answer for it, when the
  // request failed, or once one of its sheets failed to load: the one signal every surface degrades from.
  frames: Map<string, VideoFrames>;
  // Called by a strip whose sheet wouldn't load, which drops that moment's frames for good rather than retrying.
  markBroken: (moment: Moment) => void;
};

/** A moment identified as both the request and the answer carry it: one Video can be asked about twice. */
export function momentKey(moment: { video_id: number; seconds: number }): string {
  return `${moment.video_id}:${moment.seconds}`;
}

/** The frames the moments ask for, read from geometry already stored. Never makes Mentor call YouTube. */
export function useFrames(moments: Moment[], enabled: boolean): Frames {
  const [found, setFound] = useState<Map<string, VideoFrames>>(new Map());
  const [broken, setBroken] = useState<string[]>([]);
  // The moments as asked for, so re-rendering with the same ones doesn't ask again.
  const asked = JSON.stringify(moments);

  useEffect(() => {
    setBroken([]);
    if (!enabled || moments.length === 0) {
      setFound(new Map());
      return;
    }
    let current = true;
    const batches = [];
    for (let from = 0; from < moments.length; from += maxMoments) batches.push(moments.slice(from, from + maxMoments));
    void Promise.allSettled(batches.map((batch) => api.frames(batch))).then((answers) => {
      if (!current) return;
      const found = new Map<string, VideoFrames>();
      for (const answer of answers) {
        // No frames is a legitimate state, so a request that failed shows none of its own and is not retried.
        if (answer.status !== "fulfilled") continue;
        for (const video of answer.value) found.set(momentKey(video), video);
      }
      setFound(found);
    });
    return () => {
      current = false;
    };
  }, [asked, enabled]);

  const frames = new Map(found);
  for (const key of broken) frames.delete(key);
  return { frames, markBroken: (moment) => setBroken((gone) => [...gone, momentKey(moment)]) };
}

/** One Video's strip. `onActivate` makes each frame a play target, as the Sources column needs. */
export function FrameStrip({
  video,
  title,
  onBroken,
  frameClassName,
  onActivate,
}: {
  video: VideoFrames;
  // Named on the peek, which is where a frame says which Video it came from.
  title: string;
  onBroken: () => void;
  frameClassName?: string;
  onActivate?: (frame: Frame) => void;
}) {
  return (
    <span className="flex gap-0.5">
      {video.frames.map((frame) => (
        <Peek
          key={frame.seconds}
          video={video}
          frame={frame}
          title={title}
          className={frameClassName}
          onBroken={onBroken}
          onActivate={onActivate}
        />
      ))}
    </span>
  );
}

// Hover or keyboard focus opens the frame under the cursor at one fixed width, with the moment it shows.
function Peek({
  video,
  frame,
  title,
  className,
  onBroken,
  onActivate,
}: {
  video: VideoFrames;
  frame: Frame;
  title: string;
  className?: string;
  onBroken: () => void;
  onActivate?: (frame: Frame) => void;
}) {
  const at = formatDuration(Math.floor(frame.seconds));
  // Focusable either way, since focus is how the keyboard opens the preview: a frame that plays a moment is a
  // button, and one that only previews itself is an image, which is what a screen reader announces its label as.
  const style = cn(
    "block shrink-0 overflow-hidden rounded-[3px] outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
    className,
  );
  return (
    <HoverCard.Root openDelay={90} closeDelay={60}>
      <HoverCard.Trigger asChild>
        {onActivate === undefined ? (
          <span role="img" aria-label={`Frame at ${at}`} tabIndex={0} className={style}>
            <Tile video={video} frame={frame} onBroken={onBroken} />
          </span>
        ) : (
          <button
            type="button"
            aria-label={`Play ${title} at ${at}`}
            onClick={() => onActivate(frame)}
            className={cn(style, "cursor-pointer hover:opacity-80")}
          >
            <Tile video={video} frame={frame} onBroken={onBroken} />
          </button>
        )}
      </HoverCard.Trigger>
      <HoverCard.Portal>
        <HoverCard.Content
          // Supplementary to the trigger, whose label already names the moment: a bigger look, not new information.
          role="tooltip"
          side="top"
          sideOffset={6}
          style={{ width: peekWidth + 16 }}
          className="z-50 rounded-lg border bg-popover p-2 text-popover-foreground shadow-md"
        >
          <Tile video={video} frame={frame} onBroken={onBroken} className="rounded-sm" />
          <p className="mt-2 text-xs leading-5">{title}</p>
          <p className="text-xs text-muted-foreground tabular-nums">at {at}</p>
        </HoverCard.Content>
      </HoverCard.Portal>
    </HoverCard.Root>
  );
}

function Tile({
  video,
  frame,
  onBroken,
  className,
}: {
  video: VideoFrames;
  frame: Frame;
  onBroken: () => void;
  className?: string;
}) {
  return (
    <span className={cn("relative block aspect-video w-full overflow-hidden bg-muted", className)}>
      <img
        src={frame.url}
        alt=""
        aria-hidden
        onError={onBroken}
        className="absolute max-w-none"
        style={{
          width: `${video.columns * 100}%`,
          height: `${video.rows * 100}%`,
          left: `${-frame.column * 100}%`,
          top: `${-frame.row * 100}%`,
        }}
      />
    </span>
  );
}

/** The one control over frames: in the Sources panel header, and in Settings too, since it governs search as well. */
export function ThumbnailsToggle({
  settings,
  onSettings,
  className,
}: {
  settings: Settings | null;
  onSettings: (settings: Settings) => void;
  className?: string;
}) {
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  async function set(thumbnails: boolean) {
    setSaving(true);
    setFailed(null);
    try {
      onSettings(await api.updateSettings({ thumbnails }));
    } catch (error) {
      // The switch goes on showing what is saved rather than what was asked for, and says why it didn't take.
      setFailed(errorText(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <label
      title={failed ?? undefined}
      className={cn(
        "flex items-center gap-1.5 text-xs",
        failed === null ? "text-muted-foreground" : "text-destructive",
        className,
      )}
    >
      <Switch
        size="sm"
        aria-label="Thumbnails"
        checked={settings?.thumbnails ?? true}
        aria-invalid={failed !== null}
        disabled={settings === null || saving}
        onCheckedChange={(on) => void set(on)}
      />
      Thumbnails
    </label>
  );
}

/** Consecutive items from one Video, the only grouping a strip may do: it never reorders what ranking returned. */
export function runsOf<T>(items: T[], videoId: (item: T) => number): { videoId: number; lead: T; items: T[] }[] {
  const runs: { videoId: number; lead: T; items: T[] }[] = [];
  for (const item of items) {
    const last = runs.at(-1);
    if (last !== undefined && last.videoId === videoId(item)) last.items.push(item);
    else runs.push({ videoId: videoId(item), lead: item, items: [item] });
  }
  return runs;
}
