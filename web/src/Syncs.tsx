import { useCallback, useState } from "react";
import { api, errorText, type Stage, type Sync } from "./api";
import { stageLabels, usePolling } from "./ui";

const statusClass: Record<Sync["status"], string> = {
  queued: "text-stone-500",
  running: "text-blue-700",
  done: "text-green-700",
  failed: "text-red-700",
};

function countsSummary(counts: Record<Stage, number>): string {
  return (Object.keys(stageLabels) as Stage[])
    .filter((stage) => counts[stage] > 0)
    .map((stage) => `${counts[stage]} ${stageLabels[stage].toLowerCase()}`)
    .join(" · ");
}

export function Syncs() {
  const [syncs, setSyncs] = useState<Sync[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSyncs(await api.listSyncs());
      setError(null);
    } catch (e) {
      setError(`Could not load Syncs: ${errorText(e)}`);
    }
  }, []);
  usePolling(load, 2000);

  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold">Syncs</h2>
      {error && (
        <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}
      {syncs === null ? (
        <p className="mt-4 text-sm text-stone-500">Loading…</p>
      ) : syncs.length === 0 ? (
        <p className="mt-4 text-sm text-stone-500">No Syncs yet. Use Sync on a Channel above.</p>
      ) : (
        <ul className="mt-4 divide-y divide-stone-100 text-sm">
          {syncs.map((sync) => (
            <li key={sync.id} className="py-2">
              <div className="flex items-baseline justify-between gap-2">
                <span>
                  {sync.channel_name} <span className="text-stone-500">({sync.mentor_name})</span>
                </span>
                <span className={`capitalize ${statusClass[sync.status]}`}>{sync.status}</span>
              </div>
              <div className="text-xs text-stone-500">
                {[
                  sync.new_videos > 0 ? `${sync.new_videos} new` : "",
                  countsSummary(sync.stage_counts),
                  new Date(sync.finished_at ?? sync.started_at ?? sync.queued_at).toLocaleString(),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
              {sync.error && <div className="text-xs text-red-700">{sync.error}</div>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
