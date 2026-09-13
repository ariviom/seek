import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, errorText, type ChannelProposal, type Mentor } from "./api";
import { buttonClass, inputClass, quietButtonClass, useChanges, type Act } from "./ui";
import { ChannelFiltersForm, filtersSummary } from "./ChannelFilters";
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

  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold">Mentors</h2>
      {error && (
        <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}
      <fieldset disabled={busy}>
        <AddMentor act={act} onError={setError} />
        {mentors === null ? (
          <p className="mt-4 text-sm text-stone-500">Loading…</p>
        ) : mentors.length === 0 ? (
          <p className="mt-4 text-sm text-stone-500">No Mentors yet. Paste a YouTube Channel above.</p>
        ) : (
          <ul className="mt-4 space-y-4">
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
      <form onSubmit={create} className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-sm text-stone-600">
          Channel <strong>{proposal.name}</strong> → Mentor name
        </span>
        <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} aria-label="Mentor name" />
        <button className={buttonClass} type="submit" disabled={!name.trim()}>
          Add Mentor
        </button>
        <button className={quietButtonClass} type="button" onClick={() => setProposal(null)}>
          Cancel
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={lookUp} className="mt-3 flex gap-2">
      <input
        className={`${inputClass} flex-1`}
        placeholder="YouTube Channel URL or @handle"
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
  const [attaching, setAttaching] = useState("");
  const [showingVideos, setShowingVideos] = useState<number | null>(null);
  const [editingFilters, setEditingFilters] = useState<number | null>(null);

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (renaming !== null && (await act(() => api.renameMentor(mentor.id, renaming)))) setRenaming(null);
  }

  async function attach(event: FormEvent) {
    event.preventDefault();
    if (await act(() => api.attachChannel(mentor.id, attaching))) setAttaching("");
  }

  return (
    <li className="rounded-lg border border-stone-200 p-4">
      <div className="flex items-center justify-between gap-2">
        {renaming === null ? (
          <h3 className="font-medium">{mentor.name}</h3>
        ) : (
          <form onSubmit={rename} className="flex gap-2">
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
        <div className="flex gap-1">
          <button className={quietButtonClass} onClick={() => setRenaming(renaming === null ? mentor.name : null)}>
            {renaming === null ? "Rename" : "Cancel"}
          </button>
          <button
            className={`${quietButtonClass} text-red-700 hover:text-red-900`}
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
      <ul className="mt-3 divide-y divide-stone-100">
        {mentor.channels.map((channel) => (
          <li key={channel.id} className="py-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className={channel.indexed ? "" : "text-stone-400"}>
                {channel.name} <span className="font-mono text-xs text-stone-400">{channel.youtube_channel_id}</span>
                {filtersSummary(channel.filters) && (
                  <span className="block text-xs text-stone-500">Filters: {filtersSummary(channel.filters)}</span>
                )}
              </span>
              <span className="flex items-center gap-3 whitespace-nowrap">
                <button className={quietButtonClass} onClick={() => void act(() => api.startSync(channel.id))}>
                  Sync
                </button>
                <button className={quietButtonClass} onClick={() => void act(() => api.retryFailed(channel.id))}>
                  Retry failed
                </button>
                <button
                  className={quietButtonClass}
                  aria-expanded={editingFilters === channel.id}
                  onClick={() => setEditingFilters(editingFilters === channel.id ? null : channel.id)}
                >
                  Filters
                </button>
                <button
                  className={quietButtonClass}
                  aria-expanded={showingVideos === channel.id}
                  onClick={() => setShowingVideos(showingVideos === channel.id ? null : channel.id)}
                >
                  Videos
                </button>
                <label className="flex items-center gap-1.5 text-stone-600">
                  <input
                    type="checkbox"
                    checked={channel.indexed}
                    onChange={(e) => void act(() => api.setChannelIndexed(channel.id, e.target.checked))}
                  />
                  Indexed
                </label>
                {/* The server also refuses to detach a Mentor's last Channel. */}
                {mentor.channels.length > 1 && (
                  <button
                    className={quietButtonClass}
                    onClick={() => {
                      if (confirm(`Detach ${channel.name} and remove everything ingested from it?`)) {
                        void act(() => api.detachChannel(channel.id));
                      }
                    }}
                  >
                    Detach
                  </button>
                )}
              </span>
            </div>
            {editingFilters === channel.id && (
              <ChannelFiltersForm channel={channel} act={act} onDone={() => setEditingFilters(null)} />
            )}
            {showingVideos === channel.id && <ChannelVideos channelId={channel.id} />}
          </li>
        ))}
      </ul>
      <form onSubmit={attach} className="mt-2 flex gap-2">
        <input
          className={`${inputClass} flex-1`}
          placeholder="Attach another Channel URL or @handle"
          value={attaching}
          onChange={(e) => setAttaching(e.target.value)}
          aria-label={`Attach a Channel to ${mentor.name}`}
        />
        <button className={buttonClass} type="submit" disabled={!attaching.trim()}>
          Attach
        </button>
      </form>
    </li>
  );
}
