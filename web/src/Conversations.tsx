import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, type ConversationSummary, type MentorGroup } from "./api";
import {
  alertClass,
  buttonClass,
  dangerButtonClass,
  hintClass,
  inputClass,
  outlineButtonClass,
  quietButtonClass,
  sectionHeadingClass,
} from "./ui";

// Saved Conversations, most recently active first, for every Mentor Group or one. `version` changes whenever one may
// have changed elsewhere.
export function Conversations({
  groups,
  version,
  openId,
  onOpen,
  onDeleted,
}: {
  groups: MentorGroup[] | null;
  version: number;
  openId: number | null;
  onOpen: (conversation: ConversationSummary) => void;
  onDeleted: (conversationId: number) => void;
}) {
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [groupId, setGroupId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: number; title: string } | null>(null);
  const [busy, setBusy] = useState(false);
  // Counts this section's own changes, each followed by a reload.
  const [changes, setChanges] = useState(0);
  // A Group that has since been deleted shows every Conversation again.
  const shownGroupId = groups?.some((g) => g.id === groupId) ? groupId : null;

  useEffect(() => {
    let current = true;
    api
      .listConversations(shownGroupId)
      .then((listed) => {
        if (!current) return;
        setConversations(listed);
        setError(null);
      })
      .catch((e: unknown) => current && setError(`Could not load Conversations: ${errorText(e)}`));
    return () => {
      current = false;
    };
  }, [version, shownGroupId, changes]);

  async function change(run: () => Promise<unknown>): Promise<boolean> {
    setError(null);
    setBusy(true);
    try {
      await run();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(false);
      setChanges((c) => c + 1);
    }
  }

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (renaming === null) return;
    const { id, title } = renaming;
    if (await change(() => api.renameConversation(id, title))) setRenaming(null);
  }

  async function remove(conversation: ConversationSummary) {
    if (!confirm(`Delete the Conversation “${conversation.title}”?`)) return;
    if (await change(() => api.deleteConversation(conversation.id))) onDeleted(conversation.id);
  }

  return (
    <section aria-labelledby="conversations-heading">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="conversations-heading" className={sectionHeadingClass}>
          Conversations
        </h2>
        {groups !== null && groups.length > 0 && (
          <label className="flex items-center gap-2 text-sm text-pencil">
            Mentor Group
            <select
              className={inputClass}
              value={shownGroupId ?? ""}
              onChange={(e) => setGroupId(e.target.value === "" ? null : Number(e.target.value))}
            >
              <option value="">Every Group</option>
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <p className={`mt-2 ${hintClass}`}>Past chats with your Mentor Groups. Open one to read it or carry on.</p>
      {error && (
        <p role="alert" className={alertClass}>
          {error}
        </p>
      )}
      {conversations === null ? (
        error === null && <p className={`mt-5 ${hintClass}`}>Loading…</p>
      ) : conversations.length === 0 ? (
        <p className={`mt-5 ${hintClass}`}>No Conversations yet. Choose Ask on a Mentor Group to start one.</p>
      ) : (
        <ul className="mt-5 divide-y divide-rule/70 rounded-md bg-panel px-4 sm:px-5">
          {conversations.map((conversation) => (
            <li key={conversation.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3">
              <div className="min-w-0">
                {renaming?.id === conversation.id ? (
                  <form onSubmit={rename} className="flex flex-wrap gap-2">
                    <input
                      className={inputClass}
                      value={renaming.title}
                      onChange={(e) => setRenaming({ id: conversation.id, title: e.target.value })}
                      aria-label="New Conversation title"
                      maxLength={200}
                      autoFocus
                    />
                    <button className={buttonClass} type="submit" disabled={busy || !renaming.title.trim()}>
                      Save
                    </button>
                  </form>
                ) : (
                  <p className="truncate text-[15px] text-ink">{conversation.title}</p>
                )}
                <p className="text-[13px] text-pencil tabular-nums">
                  {conversation.group_name}
                  {conversation.group_id === null && " (deleted, read-only)"} ·{" "}
                  {new Date(conversation.last_message_at ?? conversation.created_at).toLocaleDateString()} ·{" "}
                  {conversation.message_count} {conversation.message_count === 1 ? "message" : "messages"}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-1">
                <button
                  className={quietButtonClass}
                  type="button"
                  onClick={() =>
                    setRenaming(renaming?.id === conversation.id ? null : { id: conversation.id, title: conversation.title })
                  }
                  disabled={busy}
                >
                  {renaming?.id === conversation.id ? "Cancel" : "Rename"}
                </button>
                <button className={dangerButtonClass} type="button" onClick={() => void remove(conversation)} disabled={busy}>
                  Delete
                </button>
                <button
                  className={`${outlineButtonClass} ml-1`}
                  type="button"
                  onClick={() => onOpen(conversation)}
                  disabled={conversation.id === openId}
                >
                  {conversation.group_id === null ? "Read" : "Open"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
