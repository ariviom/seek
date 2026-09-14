import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, errorText, type Channel, type ConversationSummary, type Group, type Scope } from "./api";
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
} from "./ui";

function parseFilter(value: string): Scope | null {
  const [kind, id] = value.split(":");
  if (kind !== "group" && kind !== "channel") return null;
  return { kind, id: Number(id) };
}

// Saved Conversations, most recently active first, for every Group and Channel or one of them. `version` changes
// whenever one may have changed elsewhere.
export function Conversations({
  groups,
  channels,
  version,
  openId,
  onOpen,
  onDeleted,
}: {
  groups: Group[] | null;
  channels: Channel[] | null;
  version: number;
  openId: number | null;
  onOpen: (conversation: ConversationSummary) => void;
  onDeleted: (conversationId: number) => void;
}) {
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  // The filter as an option value: "" for everything, else `group:<id>` or `channel:<id>`.
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: number; title: string } | null>(null);
  // Counts this section's own changes, each followed by a reload.
  const [changes, setChanges] = useState(0);
  const reload = useCallback(async () => setChanges((c) => c + 1), []);
  const { act, busy } = useChanges(reload, setError);
  // A Group or Channel that has since been deleted shows every Conversation again.
  const chosen = parseFilter(filter);
  const exists =
    chosen === null ||
    (chosen.kind === "group" ? groups?.some((g) => g.id === chosen.id) : channels?.some((c) => c.id === chosen.id));
  const shownScope = exists ? chosen : null;
  const shownFilter = shownScope === null ? "" : filter;
  const scopeKey = shownScope === null ? "" : `${shownScope.kind}:${shownScope.id}`;

  useEffect(() => {
    let current = true;
    api
      .listConversations(parseFilter(scopeKey))
      .then((listed) => {
        if (!current) return;
        setConversations(listed);
        setError(null);
      })
      .catch((e: unknown) => current && setError(`Could not load Conversations: ${errorText(e)}`));
    return () => {
      current = false;
    };
  }, [version, scopeKey, changes]);

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (renaming === null) return;
    const { id, title } = renaming;
    if (await act(() => api.renameConversation(id, title))) setRenaming(null);
  }

  async function remove(conversation: ConversationSummary) {
    if (!confirm(`Delete the Conversation “${conversation.title}”?`)) return;
    if (await act(() => api.deleteConversation(conversation.id))) onDeleted(conversation.id);
  }

  return (
    <section aria-labelledby="conversations-heading">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="conversations-heading" className={sectionHeadingClass}>
          Conversations
        </h2>
        {((groups?.length ?? 0) > 0 || (channels?.length ?? 0) > 0) && (
          <label className="flex items-center gap-2 text-sm text-pencil">
            Show
            <select className={inputClass} value={shownFilter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">Everything</option>
              {groups !== null && groups.length > 0 && (
                <optgroup label="Groups">
                  {groups.map((group) => (
                    <option key={group.id} value={`group:${group.id}`}>
                      {group.name}
                    </option>
                  ))}
                </optgroup>
              )}
              {channels !== null && channels.length > 0 && (
                <optgroup label="Channels">
                  {channels.map((channel) => (
                    <option key={channel.id} value={`channel:${channel.id}`}>
                      {channel.name}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
        )}
      </div>
      <p className={`mt-2 ${hintClass}`}>
        Past chats with your Groups and Channels. Open one to read it or carry on.
      </p>
      {error && (
        <p role="alert" className={alertClass}>
          {error}
        </p>
      )}
      {conversations === null ? (
        error === null && <p className={`mt-5 ${hintClass}`}>Loading…</p>
      ) : conversations.length === 0 ? (
        <p className={`mt-5 ${hintClass}`}>
          No Conversations yet. Choose Ask on a Group, or Ask about a search result.
        </p>
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
                  {conversation.scope.kind === "channel" ? "Channel" : "Group"} {conversation.scope.name}
                  {conversation.scope.id === null && " (deleted, read-only)"} ·{" "}
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
                  {conversation.scope.id === null ? "Read" : "Open"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
