import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, errorText, type Mentor, type MentorGroup } from "./api";
import {
  alertClass,
  buttonClass,
  chipClass,
  dangerButtonClass,
  hintClass,
  inputClass,
  outlineButtonClass,
  quietButtonClass,
  sectionHeadingClass,
  useChanges,
  type Act,
} from "./ui";

// `mentors` is null until the Mentors section has loaded. `onLoaded` receives every Group list loaded.
export function Groups({
  mentors,
  onLoaded,
  onAsk,
}: {
  mentors: Mentor[] | null;
  onLoaded: (groups: MentorGroup[]) => void;
  onAsk: (group: MentorGroup) => void;
}) {
  const [groups, setGroups] = useState<MentorGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latestLoad = useRef(0);

  const refresh = useCallback(async () => {
    // Reloads can overlap when a Mentor change lands during a Group change; only the latest may apply.
    const load = ++latestLoad.current;
    try {
      const listed = await api.listGroups();
      if (load !== latestLoad.current) return;
      setGroups(listed);
      onLoaded(listed);
    } catch (e) {
      if (load !== latestLoad.current) return;
      setGroups((current) => current ?? []);
      setError(`Could not load Mentor Groups: ${errorText(e)}`);
    }
  }, [onLoaded]);

  const { act, busy } = useChanges(refresh, setError);

  // Renaming or deleting a Mentor changes Group members; Channel changes don't.
  const mentorNames = mentors?.map((m) => `${m.id}:${m.name}`).join("\n");
  useEffect(() => {
    void refresh();
  }, [refresh, mentorNames]);

  return (
    <section aria-labelledby="groups-heading">
      <h2 id="groups-heading" className={sectionHeadingClass}>
        Mentor Groups
      </h2>
      <p className={`mt-2 ${hintClass}`}>A Group is a set of Mentors you consult together on one discipline.</p>
      {error && (
        <p role="alert" className={alertClass}>
          {error}
        </p>
      )}
      <fieldset disabled={busy} className="min-w-0">
        <AddGroup act={act} />
        {groups === null ? (
          <p className={`mt-5 ${hintClass}`}>Loading…</p>
        ) : groups.length === 0 ? (
          <p className={`mt-5 ${hintClass}`}>No Mentor Groups yet. Name one above, then pick its Mentors.</p>
        ) : (
          <ul className="mt-5 space-y-4">
            {groups.map((group) => (
              <GroupCard key={group.id} group={group} mentors={mentors ?? group.mentors} act={act} onAsk={onAsk} />
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
    <form onSubmit={create} className="mt-4 flex flex-wrap gap-2">
      <input
        className={`${inputClass} min-w-56 flex-1`}
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
function GroupCard({
  group,
  mentors,
  act,
  onAsk,
}: {
  group: MentorGroup;
  mentors: MentorGroup["mentors"];
  act: Act;
  onAsk: (group: MentorGroup) => void;
}) {
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
    <li className="rounded-md bg-panel px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {renaming === null ? (
          <h3 className="font-condensed text-[1.375rem] leading-tight font-semibold">
            {group.name}{" "}
            <span className="font-sans text-sm font-normal text-pencil">
              {group.mentors.length} {group.mentors.length === 1 ? "Mentor" : "Mentors"}
            </span>
          </h3>
        ) : (
          <form onSubmit={rename} className="flex flex-wrap gap-2">
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
          <button className={outlineButtonClass} onClick={() => onAsk(group)} disabled={group.mentors.length === 0}>
            Ask
          </button>
          <button className={quietButtonClass} onClick={() => setRenaming(renaming === null ? group.name : null)}>
            {renaming === null ? "Rename" : "Cancel"}
          </button>
          <button
            className={dangerButtonClass}
            onClick={() => {
              if (confirm(`Delete the Mentor Group ${group.name}? Its Mentors are kept, and its Conversations stay readable.`)) {
                void act(() => api.deleteGroup(group.id));
              }
            }}
          >
            Delete
          </button>
        </div>
      </div>
      {mentors.length === 0 ? (
        <p className={`mt-3 ${hintClass}`}>Add a Mentor above to include it in this Group.</p>
      ) : (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label={`Mentors in ${group.name}`}>
          {mentors.map((mentor) => (
            <li key={mentor.id}>
              <label className={chipClass}>
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
