import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, errorText, type Mentor, type MentorGroup } from "./api";
import { buttonClass, inputClass, quietButtonClass, useChanges, type Act } from "./ui";

// `mentors` is null until the Mentors section has loaded.
export function Groups({ mentors }: { mentors: Mentor[] | null }) {
  const [groups, setGroups] = useState<MentorGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latestLoad = useRef(0);

  const refresh = useCallback(async () => {
    // Reloads can overlap when a Mentor change lands during a Group change; only the latest may apply.
    const load = ++latestLoad.current;
    try {
      const listed = await api.listGroups();
      if (load === latestLoad.current) setGroups(listed);
    } catch (e) {
      if (load !== latestLoad.current) return;
      setGroups((current) => current ?? []);
      setError(`Could not load Mentor Groups: ${errorText(e)}`);
    }
  }, []);

  const { act, busy } = useChanges(refresh, setError);

  // Renaming or deleting a Mentor changes Group members; Channel changes don't.
  const mentorNames = mentors?.map((m) => `${m.id}:${m.name}`).join("\n");
  useEffect(() => {
    void refresh();
  }, [refresh, mentorNames]);

  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold">Mentor Groups</h2>
      {error && (
        <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}
      <fieldset disabled={busy}>
        <AddGroup act={act} />
        {groups === null ? (
          <p className="mt-4 text-sm text-stone-500">Loading…</p>
        ) : groups.length === 0 ? (
          <p className="mt-4 text-sm text-stone-500">No Mentor Groups yet. Name one above, then pick its Mentors.</p>
        ) : (
          <ul className="mt-4 space-y-4">
            {groups.map((group) => (
              <GroupCard key={group.id} group={group} mentors={mentors ?? group.mentors} act={act} />
            ))}
          </ul>
        )}
      </fieldset>
    </section>
  );
}

function AddGroup({ act }: { act: Act }) {
  const [name, setName] = useState("");

  async function create(event: FormEvent) {
    event.preventDefault();
    if (await act(() => api.createGroup(name))) setName("");
  }

  return (
    <form onSubmit={create} className="mt-3 flex gap-2">
      <input
        className={`${inputClass} flex-1`}
        placeholder="New Mentor Group name, e.g. Woodworking"
        value={name}
        onChange={(e) => setName(e.target.value)}
        aria-label="Mentor Group name"
      />
      <button className={buttonClass} type="submit" disabled={!name.trim()}>
        Create Group
      </button>
    </form>
  );
}

// `mentors` is every Mentor that can be ticked: all of them once loaded, else just the members.
function GroupCard({ group, mentors, act }: { group: MentorGroup; mentors: MentorGroup["mentors"]; act: Act }) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const memberIds = group.mentors.map((m) => m.id);

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (renaming !== null && (await act(() => api.renameGroup(group.id, renaming)))) setRenaming(null);
  }

  function toggle(mentorId: number, member: boolean) {
    const next = member ? [...memberIds, mentorId] : memberIds.filter((id) => id !== mentorId);
    void act(() => api.setGroupMembers(group.id, next));
  }

  return (
    <li className="rounded-lg border border-stone-200 p-4">
      <div className="flex items-center justify-between gap-2">
        {renaming === null ? (
          <h3 className="font-medium">{group.name}</h3>
        ) : (
          <form onSubmit={rename} className="flex gap-2">
            <input
              className={inputClass}
              value={renaming}
              onChange={(e) => setRenaming(e.target.value)}
              aria-label="New Mentor Group name"
            />
            <button className={buttonClass} type="submit" disabled={!renaming.trim()}>
              Save
            </button>
          </form>
        )}
        <div className="flex gap-1">
          <button className={quietButtonClass} onClick={() => setRenaming(renaming === null ? group.name : null)}>
            {renaming === null ? "Rename" : "Cancel"}
          </button>
          <button
            className={`${quietButtonClass} text-red-700 hover:text-red-900`}
            onClick={() => {
              if (confirm(`Delete the Mentor Group ${group.name}? Its Mentors are kept.`)) {
                void act(() => api.deleteGroup(group.id));
              }
            }}
          >
            Delete
          </button>
        </div>
      </div>
      {mentors.length === 0 ? (
        <p className="mt-3 text-sm text-stone-500">Add a Mentor above to include it in this Group.</p>
      ) : (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
          {mentors.map((mentor) => (
            <li key={mentor.id}>
              <label className="flex items-center gap-1.5 text-sm text-stone-700">
                <input
                  type="checkbox"
                  checked={memberIds.includes(mentor.id)}
                  onChange={(e) => toggle(mentor.id, e.target.checked)}
                />
                {mentor.name}
              </label>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
