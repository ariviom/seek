import { useEffect, useState } from "react";
import { errorText, type Stage } from "./api";

export const inputClass =
  "rounded-md border border-stone-300 px-3 py-1.5 text-sm focus:border-stone-500 focus:outline-none";
export const buttonClass =
  "rounded-md bg-stone-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-stone-700 disabled:opacity-50";
export const quietButtonClass =
  "rounded-md px-2 py-1 text-sm text-stone-600 hover:bg-stone-100 hover:text-stone-900 disabled:opacity-50";

// Runs one change at a time; resolves true when the change itself succeeded.
export type Act = (change: () => Promise<unknown>) => Promise<boolean>;

// Callers disable their controls while busy, so changes and their refreshes never interleave.
export function useChanges(refresh: () => Promise<void>, setError: (message: string | null) => void) {
  const [busy, setBusy] = useState(false);

  const act: Act = async (change) => {
    setError(null);
    setBusy(true);
    try {
      await change();
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      await refresh();
      setBusy(false);
    }
    return true;
  };

  return { act, busy };
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

// Calls `load` now and again `intervalMs` after each call settles, until unmounted.
export function usePolling(load: () => Promise<void>, intervalMs: number) {
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const tick = async () => {
      await load();
      if (active) timer = window.setTimeout(tick, intervalMs);
    };
    void tick();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [load, intervalMs]);
}
