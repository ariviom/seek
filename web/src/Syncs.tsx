import { useCallback, useState } from "react";
import { api, errorText, type Sync } from "./api";
import { useLiveList, type Reaction, type ServerEvent } from "./events";
import { StageRule } from "./StageRule";
import { alertClass, hintClass, quietButtonClass, sectionHeadingClass } from "./ui";

// As many as the API lists.
const SHOWN = 50;

const status: Record<Sync["status"], { label: string; className: string }> = {
  queued: { label: "Queued", className: "text-pencil" },
  running: { label: "Running", className: "text-[#9a6c00]" },
  done: { label: "Done", className: "text-machine" },
  failed: { label: "Failed", className: "text-oxide" },
};

function react(event: ServerEvent): Reaction<Sync> {
  if (event.type === "syncs") return "reload";
  if (event.type !== "sync") return null;
  return (syncs) =>
    [event.sync, ...syncs.filter((s) => s.id !== event.sync.id)].sort((a, b) => b.id - a.id).slice(0, SHOWN);
}

function when(sync: Sync): string {
  const time = (iso: string) =>
    new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  if (sync.finished_at) return `Finished ${time(sync.finished_at)}`;
  if (sync.started_at) return `Started ${time(sync.started_at)}`;
  return `Queued ${time(sync.queued_at)}`;
}

export function Syncs() {
  const load = useCallback(() => api.listSyncs(), []);
  const { items: syncs, error } = useLiveList(load, react);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // The new Syncs arrive as events.
  async function syncAll() {
    setStartError(null);
    setStarting(true);
    try {
      await api.syncAll();
    } catch (e) {
      setStartError(errorText(e));
    } finally {
      setStarting(false);
    }
  }

  return (
    <section aria-labelledby="syncs-heading">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="syncs-heading" className={sectionHeadingClass}>
          Syncs
        </h2>
        <button className={quietButtonClass} type="button" onClick={() => void syncAll()} disabled={starting}>
          Sync all
        </button>
      </div>
      {error !== null && <p role="alert" className={alertClass}>Could not load Syncs: {errorText(error)}</p>}
      {startError !== null && <p role="alert" className={alertClass}>Could not start the Syncs: {startError}</p>}
      {syncs === null ? (
        error === null && <p className={`mt-4 ${hintClass}`}>Loading…</p>
      ) : syncs.length === 0 ? (
        <p className={`mt-4 ${hintClass}`}>No Syncs yet. Sync a Channel to fetch its Videos.</p>
      ) : (
        <ol className="mt-4 space-y-3">
          {syncs.map((sync) => {
            const active = sync.status === "queued" || sync.status === "running";
            return (
              <li key={sync.id} className={active ? "rounded-md bg-panel p-4" : "px-1 py-2"}>
                <div className="flex items-baseline justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{sync.channel_name}</p>
                  </div>
                  <span className={`shrink-0 text-sm font-medium ${status[sync.status].className}`}>
                    {status[sync.status].label}
                  </span>
                </div>
                {sync.status === "running" && sync.fetching && (
                  <p className="mt-1 truncate text-[13px] text-pencil" title={sync.fetching}>
                    Fetching {sync.fetching}
                  </p>
                )}
                <div className="mt-2">
                  <StageRule counts={sync.stage_counts} detailed={active} />
                </div>
                <div className="mt-1.5 flex flex-wrap justify-between gap-x-3 text-[13px] text-pencil">
                  <span>{when(sync)}</span>
                  {sync.new_videos > 0 && (
                    <span>
                      {sync.new_videos} new {sync.new_videos === 1 ? "Video" : "Videos"}
                    </span>
                  )}
                </div>
                {sync.error && <p className="mt-1 text-[13px] text-oxide">{sync.error}</p>}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
