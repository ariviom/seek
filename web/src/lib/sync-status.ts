import { useEffect, useState } from "react";
import type { Sync } from "@/lib/api";
import { plural } from "@/lib/format";

// What a Sync is doing now, read off the record so a reload shows the same thing: how many Videos it has finished
// with, how many of those can be searched, how many are left, and how fast the work is going.
export type SyncProgress = {
  label: string;
  // Videos this Sync has finished with, whether they were indexed or failed.
  processed: number;
  // Of those, the ones a question can now be answered from.
  ready: number;
  failed: number;
  total: number;
  remaining: number;
  // Videos per second over the interval the Sync is measuring, or null while it is still warming up.
  rate: number | null;
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

// The observed rate, in the unit that reads best: Videos a minute while they come faster than that, and
// minutes a Video once they don't, which is what a long transcript fetch actually feels like.
export function rateText(perSecond: number): string {
  const perMinute = perSecond * 60;
  if (perMinute >= 1) return `${round(perMinute)} videos/min`;
  return `${round(1 / perMinute)} min/video`;
}

function round(n: number): number {
  return n < 10 ? Number(n.toFixed(1)) : Math.round(n);
}

function tally(sync: Sync): { processed: number; ready: number; failed: number; remaining: number; total: number } {
  // Both counted per Video by the server, so a Video processed twice is never in them twice and the total never
  // exceeds the Channel's Videos. A retry-failed Sync puts the failures it clears back among the remaining.
  const remaining = sync.remaining_videos;
  const processed = sync.completed_videos;
  const failed = sync.failed_videos;
  return { processed, ready: processed - failed, failed, remaining, total: processed + remaining };
}

export function syncProgress(sync: Sync, now: number): SyncProgress {
  const { processed, ready, failed, remaining, total } = tally(sync);
  // Only a running Sync is going at any rate at all. Both ends of the measurement moved together when this run
  // was claimed, so a Sync resumed after a restart warms up again rather than crediting old work to new time.
  const measured = processed - sync.counted_from;
  const elapsed = sync.started_at === null ? 0 : (now - Date.parse(sync.started_at)) / 1000;
  const rate =
    sync.status === "running" && measured >= ENOUGH_FOR_A_RATE && elapsed > 0 ? measured / elapsed : null;
  const secondsLeft = rate !== null && remaining > 0 ? remaining / rate : null;

  const progress: Omit<SyncProgress, "label"> = {
    processed,
    ready,
    failed,
    total,
    remaining,
    rate,
    secondsLeft,
    fetching: sync.fetching,
  };
  if (sync.status === "queued") return { ...progress, label: "Queued" };
  if (sync.status === "failed") return { ...progress, label: `Sync failed: ${sync.error ?? "unknown error"}` };
  if (sync.status === "done") return { ...progress, label: "Synced" };
  const parts = ["Syncing", ...syncDetails(progress)];
  if (sync.fetching !== null) parts.push(`fetching “${sync.fetching}”`);
  return { ...progress, label: parts.join(" · ") };
}

// What a running Sync has to report, in the order it matters. Every view composes its line from these, so the
// Library, the Channel and the Sync never disagree about the same Sync.
export function syncDetails(progress: Omit<SyncProgress, "label">): string[] {
  // Nothing is counted or estimated until discovery has found the Videos there are to get through.
  if (progress.total === 0) return ["looking for new videos"];
  const parts = [`${progress.processed} of ${progress.total} videos`];
  if (progress.failed > 0) parts.push(`${progress.ready} ready, ${progress.failed} failed`);
  if (progress.remaining > 0) parts.push(progress.rate === null ? "measuring speed" : rateText(progress.rate));
  if (progress.secondsLeft !== null) parts.push(`about ${timeLeft(progress.secondsLeft)} left`);
  return parts;
}

// The compact form for a list row: counts only, so it needs no clock.
export function syncCounts(sync: Sync): string {
  if (sync.status === "queued") return "Queued";
  const { processed, total } = tally(sync);
  return total === 0 ? "Syncing" : `Syncing ${processed}/${total}`;
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
