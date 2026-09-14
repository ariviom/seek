import type { Stage } from "@/lib/api";

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
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
