import { useCallback, useState } from "react";
import { api, errorText, type Sync } from "@/lib/api";
import { useLiveList, type Reaction, type ServerEvent } from "@/lib/events";
import { formatWhen } from "@/lib/format";

// As many as the API lists.
const SHOWN = 50;

export const syncStatus: Record<Sync["status"], { label: string; dot: string }> = {
  queued: { label: "Queued", dot: "bg-zinc-400" },
  running: { label: "Running", dot: "bg-amber-500 motion-safe:animate-pulse" },
  done: { label: "Done", dot: "bg-emerald-500" },
  failed: { label: "Failed", dot: "bg-red-500" },
};

function react(event: ServerEvent): Reaction<Sync> {
  if (event.type === "syncs") return "reload";
  if (event.type !== "sync") return null;
  return (syncs) =>
    [event.sync, ...syncs.filter((s) => s.id !== event.sync.id)].sort((a, b) => b.id - a.id).slice(0, SHOWN);
}

export function when(sync: Sync): string {
  if (sync.finished_at) return `Finished ${formatWhen(sync.finished_at)}`;
  if (sync.started_at) return `Started ${formatWhen(sync.started_at)}`;
  return `Queued ${formatWhen(sync.queued_at)}`;
}

// Loaded once in App and handed to the rail, the list column, and the page, so all three see an event at once.
export function useSyncs() {
  const load = useCallback(() => api.listSyncs(), []);
  return useLiveList(load, react);
}

// "Sync all" lives in the list column header but reports its error inside the list, so the state is held above both.
export function useSyncAll() {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The new Syncs arrive as events.
  const run = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      await api.syncAll();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setStarting(false);
    }
  }, []);

  return { run, starting, error };
}
