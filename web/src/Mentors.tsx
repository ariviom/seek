import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type ChannelProposal, type Mentor } from "./api";

const input = "rounded-md border border-stone-300 px-3 py-1.5 text-sm focus:border-stone-500 focus:outline-none";
const button = "rounded-md bg-stone-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-stone-700 disabled:opacity-50";
const quietButton = "rounded-md px-2 py-1 text-sm text-stone-600 hover:bg-stone-100 hover:text-stone-900";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function Mentors() {
  const [mentors, setMentors] = useState<Mentor[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setMentors(await api.listMentors());
  }, []);

  // Runs a change, then reloads the list; any failure is shown once at the top.
  const act = useCallback(
    async (change: () => Promise<unknown>): Promise<boolean> => {
      setError(null);
      try {
        await change();
        await refresh();
        return true;
      } catch (e) {
        setError(errorText(e));
        return false;
      }
    },
    [refresh],
  );

  useEffect(() => {
    refresh().catch((e: unknown) => setError(errorText(e)));
  }, [refresh]);

  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold">Mentors</h2>
      {error && (
        <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}
      <AddMentor act={act} />
      {mentors === null ? (
        <p className="mt-4 text-sm text-stone-500">Loading…</p>
      ) : mentors.length === 0 ? (
        <p className="mt-4 text-sm text-stone-500">No Mentors yet. Paste a YouTube channel above.</p>
      ) : (
        <ul className="mt-4 space-y-4">
          {mentors.map((mentor) => (
            <MentorCard key={mentor.id} mentor={mentor} act={act} />
          ))}
        </ul>
      )}
    </section>
  );
}

type Act = (change: () => Promise<unknown>) => Promise<boolean>;

function AddMentor({ act }: { act: Act }) {
  const [channel, setChannel] = useState("");
  const [proposal, setProposal] = useState<ChannelProposal | null>(null);
  const [name, setName] = useState("");

  async function resolve(event: FormEvent) {
    event.preventDefault();
    await act(async () => {
      const found = await api.resolveChannel(channel);
      setProposal(found);
      setName(found.name);
    });
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
        <input className={input} value={name} onChange={(e) => setName(e.target.value)} aria-label="Mentor name" />
        <button className={button} type="submit" disabled={!name.trim()}>
          Add Mentor
        </button>
        <button className={quietButton} type="button" onClick={() => setProposal(null)}>
          Cancel
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={resolve} className="mt-3 flex gap-2">
      <input
        className={`${input} flex-1`}
        placeholder="YouTube channel URL or @handle"
        value={channel}
        onChange={(e) => setChannel(e.target.value)}
        aria-label="YouTube channel URL or handle"
      />
      <button className={button} type="submit" disabled={!channel.trim()}>
        Look up
      </button>
    </form>
  );
}

function MentorCard({ mentor, act }: { mentor: Mentor; act: Act }) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const [attaching, setAttaching] = useState("");

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
              className={input}
              value={renaming}
              onChange={(e) => setRenaming(e.target.value)}
              aria-label="New Mentor name"
            />
            <button className={button} type="submit" disabled={!renaming.trim()}>
              Save
            </button>
          </form>
        )}
        <div className="flex gap-1">
          <button className={quietButton} onClick={() => setRenaming(renaming === null ? mentor.name : null)}>
            {renaming === null ? "Rename" : "Cancel"}
          </button>
          <button
            className={`${quietButton} text-red-700 hover:text-red-900`}
            onClick={() => {
              if (confirm(`Delete ${mentor.name} and everything ingested from their Channels?`)) {
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
          <li key={channel.id} className="flex items-center justify-between gap-2 py-2 text-sm">
            <span className={channel.indexed ? "" : "text-stone-400"}>
              {channel.name} <span className="font-mono text-xs text-stone-400">{channel.youtube_channel_id}</span>
            </span>
            <span className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-stone-600">
                <input
                  type="checkbox"
                  checked={channel.indexed}
                  onChange={(e) => void act(() => api.setChannelIndexed(channel.id, e.target.checked))}
                />
                Indexed
              </label>
              {mentor.channels.length > 1 && (
                <button className={quietButton} onClick={() => void act(() => api.detachChannel(channel.id))}>
                  Detach
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
      <form onSubmit={attach} className="mt-2 flex gap-2">
        <input
          className={`${input} flex-1`}
          placeholder="Attach another channel URL or @handle"
          value={attaching}
          onChange={(e) => setAttaching(e.target.value)}
          aria-label={`Attach a channel to ${mentor.name}`}
        />
        <button className={button} type="submit" disabled={!attaching.trim()}>
          Attach
        </button>
      </form>
    </li>
  );
}
