import { useEffect, useState } from "react";
import type { Sync } from "@/lib/api";
import { plural } from "@/lib/format";

// What a Sync is doing now, read off the record so a reload shows the same thing: how many Videos it has finished
// with, how many are left, and how long that will take at the rate it has managed so far.
export type SyncProgress = {
  label: string;
  completed: number;
  total: number;
  remaining: number;
  secondsLeft: number | null;
  fetching: string | null;
};

// Below this an estimate says more about the first Video than about the Sync.
const ENOUGH_FOR_A_RATE = 3;

export function isRunning(sync: Sync): boolean {
  return sync.status === "queued" || sync.status === "running";
}

// The Sync a Channel has running, else the one it has queued, if any. A Sync queued behind a running one (a retry
// or the timer) carries only the counts it was queued with, so the running one is the one to show.
export function channelSync(syncs: Sync[] | null, channelId: number): Sync | null {
  const own = syncs?.filter((sync) => sync.channel_id === channelId) ?? [];
  return own.find((sync) => sync.status === "running") ?? own.find((sync) => sync.status === "queued") ?? null;
}

export function timeLeft(seconds: number): string {
  if (seconds < 90) return "a minute";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  const hours = seconds / 3600;
  return `${hours < 10 ? Number(hours.toFixed(1)) : Math.round(hours)} h`;
}

function tally(sync: Sync): { completed: number; remaining: number; total: number } {
  const counts = sync.stage_counts;
  const remaining = counts.discovered + counts.transcript_fetched + counts.segmented + counts.embedded;
  const completed = sync.completed_videos;
  return { completed, remaining, total: completed + remaining };
}

export function syncProgress(sync: Sync, now: number): SyncProgress {
  const { completed, remaining, total } = tally(sync);
  const elapsed = sync.started_at === null ? 0 : (now - Date.parse(sync.started_at)) / 1000;
  const secondsLeft =
    completed >= ENOUGH_FOR_A_RATE && elapsed > 0 && remaining > 0 ? (remaining * elapsed) / completed : null;

  const progress: Omit<SyncProgress, "label"> = {
    completed,
    total,
    remaining,
    secondsLeft,
    fetching: sync.fetching,
  };
  if (sync.status === "queued") return { ...progress, label: "Queued" };
  if (sync.status === "failed") return { ...progress, label: `Sync failed: ${sync.error ?? "unknown error"}` };
  if (sync.status === "done") return { ...progress, label: "Synced" };
  const parts = [`Syncing · ${completed} of ${total} ready`];
  if (secondsLeft !== null) parts.push(`about ${timeLeft(secondsLeft)} left`);
  if (sync.fetching !== null) parts.push(`fetching “${sync.fetching}”`);
  return { ...progress, label: parts.join(" · ") };
}

// The compact form for a list row: counts only, so it needs no clock.
export function syncCounts(sync: Sync): string {
  if (sync.status === "queued") return "Queued";
  const { completed, total } = tally(sync);
  return `Syncing ${completed}/${total}`;
}

// How many Videos a scope can already answer from while some of its Channels sync.
export function syncingNote(names: string[], ready: number): string | null {
  if (names.length === 0) return null;
  const who = names.length === 1 ? names[0] : `${names.length} channels`;
  return `Syncing ${who}; answers use the ${plural(ready, "video")} ready so far.`;
}

// The clock the countdown reads, ticking every `seconds` while a Sync is queued or running and standing still
// otherwise, so nothing re-renders once there is nothing left to count down.
export function useNow(seconds: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (seconds <= 0) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), seconds * 1000);
    return () => window.clearInterval(timer);
  }, [seconds]);
  return now;
}
