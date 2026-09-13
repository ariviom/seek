import { useState, type FormEvent } from "react";
import { api, type Channel, type ChannelFilters } from "./api";
import { buttonClass, inputClass, quietButtonClass, type Act } from "./ui";

const noFilters: ChannelFilters = { published_after: null, published_before: null, playlist_id: null, most_recent: null };

export function filtersSummary(filters: ChannelFilters): string {
  return [
    filters.published_after && `from ${filters.published_after}`,
    filters.published_before && `until ${filters.published_before}`,
    filters.playlist_id && `playlist ${filters.playlist_id}`,
    filters.most_recent !== null && `${filters.most_recent} most recent`,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function ChannelFiltersForm({ channel, act, onDone }: { channel: Channel; act: Act; onDone: () => void }) {
  const [after, setAfter] = useState(channel.filters.published_after ?? "");
  const [before, setBefore] = useState(channel.filters.published_before ?? "");
  const [playlist, setPlaylist] = useState(channel.filters.playlist_id ?? "");
  const [mostRecent, setMostRecent] = useState(channel.filters.most_recent?.toString() ?? "");

  async function save(filters: ChannelFilters) {
    if (await act(() => api.setChannelFilters(channel.id, filters))) onDone();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void save({
      published_after: after || null,
      published_before: before || null,
      playlist_id: playlist.trim() || null,
      most_recent: mostRecent ? Number(mostRecent) : null,
    });
  }

  const label = "flex flex-col gap-1 text-xs text-stone-600";
  return (
    <form onSubmit={submit} className="mt-2 rounded-md bg-stone-50 p-3">
      <div className="grid grid-cols-2 gap-3">
        <label className={label}>
          Published on or after
          <input className={inputClass} type="date" value={after} onChange={(e) => setAfter(e.target.value)} />
        </label>
        <label className={label}>
          Published on or before
          <input className={inputClass} type="date" value={before} onChange={(e) => setBefore(e.target.value)} />
        </label>
        <label className={label}>
          Playlist id
          <input
            className={inputClass}
            placeholder="PL…"
            value={playlist}
            onChange={(e) => setPlaylist(e.target.value)}
          />
        </label>
        <label className={label}>
          Most recent Videos
          <input
            className={inputClass}
            type="number"
            min={1}
            step={1}
            placeholder="All"
            value={mostRecent}
            onChange={(e) => setMostRecent(e.target.value)}
          />
        </label>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button className={buttonClass} type="submit">
          Save filters
        </button>
        <button className={quietButtonClass} type="button" onClick={() => void save(noFilters)}>
          Clear
        </button>
        <button className={quietButtonClass} type="button" onClick={onDone}>
          Cancel
        </button>
        <span className="text-xs text-stone-500">Applied by the next Sync.</span>
      </div>
    </form>
  );
}
