import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, errorText, type Channel, type ChannelProposal, type Mentor } from "./api";
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

export function Mentors({ onLoaded }: { onLoaded: (mentors: Mentor[]) => void }) {
  const [mentors, setMentors] = useState<Mentor[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const listed = await api.listMentors();
      setMentors(listed);
      onLoaded(listed);
    } catch (e) {
      setMentors((current) => current ?? []);
      setError(`Could not load Mentors: ${errorText(e)}`);
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
    <section aria-labelledby="mentors-heading">
      <h2 id="mentors-heading" className={sectionHeadingClass}>
        Mentors
      </h2>
      {error && (
        <p role="alert" className={alertClass}>
          {error}
        </p>
      )}
      <fieldset disabled={busy} className="min-w-0">
        <AddMentor act={act} onError={setError} />
        {mentors === null ? (
          <p className={`mt-5 ${hintClass}`}>Loading…</p>
        ) : mentors.length === 0 ? (
          <p className={`mt-5 ${hintClass}`}>
            No Mentors yet. Paste a creator's YouTube channel above to add the first one.
          </p>
        ) : (
          <ul className="mt-5 space-y-4">
            {mentors.map((mentor) => (
              <MentorCard key={mentor.id} mentor={mentor} act={act} />
            ))}
          </ul>
        )}
      </fieldset>
    </section>
  );
}

function AddMentor({ act, onError }: { act: Act; onError: (message: string | null) => void }) {
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
    if (await act(() => api.createMentor(name, proposal.youtube_channel_id))) {
      setProposal(null);
      setChannel("");
    }
  }

  if (proposal) {
    return (
      <form onSubmit={create} className="mt-4 rounded-md border border-machine/40 bg-panel p-4">
        <p className="text-[15px]">
          Found the channel <strong className="font-semibold">{proposal.name}</strong>. Name the Mentor who teaches
          on it:
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            className={`${inputClass} min-w-48 flex-1`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="Mentor name"
          />
          <button className={buttonClass} type="submit" disabled={!name.trim()}>
            Add Mentor
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

function MentorCard({ mentor, act }: { mentor: Mentor; act: Act }) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const [attaching, setAttaching] = useState<string | null>(null);

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (renaming !== null && (await act(() => api.renameMentor(mentor.id, renaming)))) setRenaming(null);
  }

  async function attach(event: FormEvent) {
    event.preventDefault();
    if (attaching !== null && (await act(() => api.attachChannel(mentor.id, attaching)))) setAttaching(null);
  }

  return (
    <li className="rounded-md bg-panel px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {renaming === null ? (
          <h3 className="font-condensed text-[1.375rem] leading-tight font-semibold">{mentor.name}</h3>
        ) : (
          <form onSubmit={rename} className="flex flex-wrap gap-2">
            <input
              className={inputClass}
              value={renaming}
              onChange={(e) => setRenaming(e.target.value)}
              aria-label="New Mentor name"
            />
            <button className={buttonClass} type="submit" disabled={!renaming.trim()}>
              Save
            </button>
          </form>
        )}
        <div className="flex flex-wrap gap-1">
          <button
            className={quietButtonClass}
            aria-expanded={attaching !== null}
            onClick={() => setAttaching(attaching === null ? "" : null)}
          >
            Attach Channel
          </button>
          <button className={quietButtonClass} onClick={() => setRenaming(renaming === null ? mentor.name : null)}>
            {renaming === null ? "Rename" : "Cancel"}
          </button>
          <button
            className={dangerButtonClass}
            onClick={() => {
              if (confirm(`Delete ${mentor.name}, everything ingested from their Channels, and their Mentor Group memberships?`)) {
                void act(() => api.deleteMentor(mentor.id));
              }
            }}
          >
            Delete
          </button>
        </div>
      </div>
      <ul className="mt-3">
        {mentor.channels.map((channel) => (
          <ChannelRow key={channel.id} channel={channel} canDetach={mentor.channels.length > 1} act={act} />
        ))}
      </ul>
      {attaching !== null && (
        <form onSubmit={attach} className="mt-3 flex flex-wrap gap-2 border-t border-rule pt-3">
          <input
            className={`${inputClass} min-w-48 flex-1`}
            placeholder="Another YouTube channel URL or @handle"
            value={attaching}
            onChange={(e) => setAttaching(e.target.value)}
            aria-label={`Attach a Channel to ${mentor.name}`}
            autoFocus
          />
          <button className={buttonClass} type="submit" disabled={!attaching.trim()}>
            Attach
          </button>
          <button className={quietButtonClass} type="button" onClick={() => setAttaching(null)}>
            Cancel
          </button>
        </form>
      )}
    </li>
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

function ChannelRow({ channel, canDetach, act }: { channel: Channel; canDetach: boolean; act: Act }) {
  const [panel, setPanel] = useState<"filters" | "videos" | null>(null);
  const filters = filtersSummary(channel.filters);
  const toggle = (next: "filters" | "videos") => setPanel(panel === next ? null : next);

  return (
    <li className="border-t border-rule py-3 first:border-t-0 first:pt-1 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <p className={`font-medium ${channel.indexed ? "" : "text-pencil"}`}>
            <a
              className="decoration-machine/50 underline-offset-2 hover:underline"
              href={`https://www.youtube.com/channel/${channel.youtube_channel_id}`}
              target="_blank"
              rel="noreferrer"
            >
              {channel.name}
            </a>
            {!channel.indexed && <span className="ml-2 text-[13px] font-normal">Not indexed, so left out of search</span>}
          </p>
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
        <label className="ml-1 flex items-center gap-1.5 px-1 text-[15px] text-pencil">
          <input
            type="checkbox"
            checked={channel.indexed}
            onChange={(e) => void act(() => api.setChannelIndexed(channel.id, e.target.checked))}
          />
          Indexed
        </label>
        {/* The server also refuses to detach a Mentor's last Channel. */}
        {canDetach && (
          <button
            className={`${dangerButtonClass} ml-auto`}
            onClick={() => {
              if (confirm(`Detach ${channel.name} and remove everything ingested from it?`)) {
                void act(() => api.detachChannel(channel.id));
              }
            }}
          >
            Detach
          </button>
        )}
      </div>
      {panel === "filters" && <ChannelFiltersForm channel={channel} act={act} onDone={() => setPanel(null)} />}
      {panel === "videos" && <ChannelVideos channelId={channel.id} />}
    </li>
  );
}
