import type { Stage } from "@/lib/api";

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

// The one date format the lists and pages share; "never" when nothing has happened yet.
export function formatWhen(at: string | null): string {
  if (at === null) return "never";
  return new Date(at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// Grouped the reader's way: these are counts to compare, not identifiers.
export function formatCount(n: number): string {
  return n.toLocaleString();
}

// A file's size as a person reads one: megabytes to one place, kilobytes under one.
export function formatSize(bytes: number): string {
  const megabytes = bytes / 1_000_000;
  return megabytes >= 1 ? `${megabytes.toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

export function plural(n: number, noun: string): string {
  return `${n} ${n === 1 ? noun : `${noun}s`}`;
}

export const stageLabels: Record<Stage, string> = {
  discovered: "Discovered",
  transcript_fetched: "Transcript fetched",
  segmented: "Segmented",
  embedded: "Embedded",
  done: "Done",
  failed: "Failed",
  excluded: "Excluded",
};

// How often a Channel or a Playlist is checked, by the Select value that picks it.
export const checkLabels: Record<string, string> = { "6": "Every 6 hours", "24": "Daily", "168": "Weekly", off: "Off" };
