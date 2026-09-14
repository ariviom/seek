import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, errorText, type Channel, type ChannelProposal } from "./api";
import {
  alertClass,
  buttonClass,
  dangerButtonClass,
  hintClass,
  inputClass,
  outlineButtonClass,
  quietButtonClass,
  sectionHeadingClass,
  useChanges,
  type Act,
} from "./ui";
import { ChannelFiltersForm, filtersSummary } from "./ChannelFilters";
import { useServerEvents } from "./events";
import { ChannelVideos } from "./Videos";

export function Channels({ onLoaded }: { onLoaded: (channels: Channel[]) => void }) {
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const listed = await api.listChannels();
      setChannels(listed);
      onLoaded(listed);
    } catch (e) {
      setChannels((current) => current ?? []);
      setError(`Could not load Channels: ${errorText(e)}`);
    }
  }, [onLoaded]);

  const { act, busy } = useChanges(refresh, setError);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Channel counts follow Syncs and Video changes, at most one reload a second while they stream in.
  const countsTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(countsTimer.current), []);
  useServerEvents((event) => {
    if (event.type !== "sync" && event.type !== "videos" && event.type !== "ready") return;
    if (countsTimer.current !== undefined) return;
    countsTimer.current = window.setTimeout(() => {
      countsTimer.current = undefined;
      void refresh();
    }, 1000);
  });

  return (
    <section aria-labelledby="channels-heading">
      <h2 id="channels-heading" className={sectionHeadingClass}>
        Channels
      </h2>
      {error && (
        <p role="alert" className={alertClass}>
          {error}
        </p>
      )}
      <fieldset disabled={busy} className="min-w-0">
        <AddChannel act={act} onError={setError} />
        {channels === null ? (
          <p className={`mt-5 ${hintClass}`}>Loading…</p>
        ) : channels.length === 0 ? (
          <p className={`mt-5 ${hintClass}`}>
            No Channels yet. Paste a YouTube channel above to add the first one.
          </p>
        ) : (
          <ul className="mt-5 space-y-4">
            {channels.map((channel) => (
              <ChannelRow key={channel.id} channel={channel} act={act} />
            ))}
          </ul>
        )}
      </fieldset>
    </section>
  );
}

function AddChannel({ act, onError }: { act: Act; onError: (message: string | null) => void }) {
  const [channel, setChannel] = useState("");
  const [proposal, setProposal] = useState<ChannelProposal | null>(null);
  const [name, setName] = useState("");
  const [looking, setLooking] = useState(false);

  async function lookUp(event: FormEvent) {
    event.preventDefault();
    onError(null);
    setLooking(true);
    try {
      const found = await api.resolveChannel(channel);
      setProposal(found);
      setName(found.name);
    } catch (e) {
      onError(errorText(e));
    } finally {
      setLooking(false);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!proposal) return;
    if (await act(() => api.createChannel(proposal.youtube_channel_id, name))) {
      setProposal(null);
      setChannel("");
    }
  }

  if (proposal) {
    return (
      <form onSubmit={create} className="mt-4 rounded-md border border-machine/40 bg-panel p-4">
        <p className="text-[15px]">
          Found the channel <strong className="font-semibold">{proposal.name}</strong>. Name it as you'd like it
          shown:
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            className={`${inputClass} min-w-48 flex-1`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="Channel name"
          />
          <button className={buttonClass} type="submit" disabled={!name.trim()}>
            Add Channel
          </button>
          <button className={quietButtonClass} type="button" onClick={() => setProposal(null)}>
            Cancel
          </button>
        </div>
      </form>
    );
  }

  return (
    <form onSubmit={lookUp} className="mt-4 flex flex-wrap gap-2">
      <input
        className={`${inputClass} min-w-56 flex-1`}
        placeholder="YouTube channel URL or @handle"
        value={channel}
        onChange={(e) => setChannel(e.target.value)}
        aria-label="YouTube Channel URL or handle"
      />
      <button className={buttonClass} type="submit" disabled={!channel.trim() || looking}>
        {looking ? "Looking up…" : "Look up"}
      </button>
    </form>
  );
}

function channelCounts(channel: Channel): string {
  const parts = [`${channel.indexed_videos} ${channel.indexed_videos === 1 ? "Video" : "Videos"} searchable`];
  if (channel.failed_videos > 0) parts.push(`${channel.failed_videos} failed`);
  if (channel.excluded_videos > 0) parts.push(`${channel.excluded_videos} excluded`);
  const synced = channel.last_synced_at && new Date(channel.last_synced_at);
  parts.push(
    synced
      ? `synced ${synced.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`
      : "never synced",
  );
  return parts.join(" · ");
}

function ChannelRow({ channel, act }: { channel: Channel; act: Act }) {
  const [panel, setPanel] = useState<"filters" | "videos" | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const filters = filtersSummary(channel.filters);
  const toggle = (next: "filters" | "videos") => setPanel(panel === next ? null : next);

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (renaming !== null && (await act(() => api.renameChannel(channel.id, renaming)))) setRenaming(null);
  }

  return (
    <li className="rounded-md bg-panel px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          {renaming === null ? (
            <p className={`font-medium ${channel.indexed ? "" : "text-pencil"}`}>
              <a
                className="decoration-machine/50 underline-offset-2 hover:underline"
                href={`https://www.youtube.com/channel/${channel.youtube_channel_id}`}
                target="_blank"
                rel="noreferrer"
              >
                {channel.name}
              </a>
              {!channel.indexed && (
                <span className="ml-2 text-[13px] font-normal">Not indexed, so left out of search</span>
              )}
            </p>
          ) : (
            <form onSubmit={rename} className="flex flex-wrap gap-2">
              <input
                className={inputClass}
                value={renaming}
                onChange={(e) => setRenaming(e.target.value)}
                aria-label="New Channel name"
              />
              <button className={buttonClass} type="submit" disabled={!renaming.trim()}>
                Save
              </button>
            </form>
          )}
          <p className="text-[13px] text-pencil tabular-nums">{channelCounts(channel)}</p>
          {filters && <p className="text-[13px] text-pencil">Filtered to {filters}</p>}
        </div>
        <button className={outlineButtonClass} onClick={() => void act(() => api.startSync(channel.id))}>
          Sync
        </button>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-1 gap-y-1">
        <button className={quietButtonClass} onClick={() => void act(() => api.retryFailed(channel.id))}>
          Retry failed
        </button>
        <button className={quietButtonClass} aria-expanded={panel === "filters"} onClick={() => toggle("filters")}>
          Filters
        </button>
        <button className={quietButtonClass} aria-expanded={panel === "videos"} onClick={() => toggle("videos")}>
          Videos
        </button>
        <button className={quietButtonClass} onClick={() => setRenaming(renaming === null ? channel.name : null)}>
          {renaming === null ? "Rename" : "Cancel"}
        </button>
        <label className="ml-1 flex items-center gap-1.5 px-1 text-[15px] text-pencil">
          <input
            type="checkbox"
            checked={channel.indexed}
            onChange={(e) => void act(() => api.setChannelIndexed(channel.id, e.target.checked))}
          />
          Indexed
        </label>
        <button
          className={`${dangerButtonClass} ml-auto`}
          onClick={() => {
            if (confirm(`Delete ${channel.name}, everything ingested from it, and its Group memberships?`)) {
              void act(() => api.deleteChannel(channel.id));
            }
          }}
        >
          Delete
        </button>
      </div>
      {panel === "filters" && <ChannelFiltersForm channel={channel} act={act} onDone={() => setPanel(null)} />}
      {panel === "videos" && <ChannelVideos channelId={channel.id} />}
    </li>
  );
}
