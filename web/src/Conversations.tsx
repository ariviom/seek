import { useEffect, useState } from "react";
import { api, errorText, type ConversationSummary, type MentorGroup } from "./api";
import { alertClass, hintClass, inputClass, outlineButtonClass, sectionHeadingClass } from "./ui";

// Saved Conversations, most recently active first, for every Mentor Group or one. `version` changes whenever one may
// have changed.
export function Conversations({
  groups,
  version,
  openId,
  onOpen,
}: {
  groups: MentorGroup[] | null;
  version: number;
  openId: number | null;
  onOpen: (conversation: ConversationSummary) => void;
}) {
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [groupId, setGroupId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
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
  }, [version, shownGroupId]);

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
                <p className="truncate text-[15px] text-ink">{conversation.title}</p>
                <p className="text-[13px] text-pencil tabular-nums">
                  {conversation.group_name}
                  {conversation.group_id === null && " (deleted, read-only)"} ·{" "}
                  {new Date(conversation.last_message_at ?? conversation.created_at).toLocaleDateString()} ·{" "}
                  {conversation.message_count} {conversation.message_count === 1 ? "message" : "messages"}
                </p>
              </div>
              <button
                className={outlineButtonClass}
                type="button"
                onClick={() => onOpen(conversation)}
                disabled={conversation.id === openId}
              >
                {conversation.group_id === null ? "Read" : "Open"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
