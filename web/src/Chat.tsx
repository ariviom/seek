import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  api,
  errorText,
  type ChatMessage,
  type ChatStreamEvent,
  type Citation,
  type ClaudeCli,
  type ConversationDetail,
  type MentorGroup,
} from "./api";
import { CitationPlayer, playOnPlainClick, usePlayer, type PlayerCitation } from "./Player";
import { alertClass, buttonClass, hintClass, inputClass, quietButtonClass, sectionHeadingClass } from "./ui";

type ToolActivity = {
  callId: string;
  name: string;
  arguments: Record<string, unknown>;
  state: "running" | "ok" | "error";
};
type Entry =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      text: string;
      tools: ToolActivity[];
      // Known once the answer is saved.
      citations: Citation[];
      state: "streaming" | "done" | "failed";
      error: string | null;
    };
type Answer = Extract<Entry, { role: "assistant" }>;

const defaultModelLabel = "Claude CLI default";
// Claude CLI aliases; null keeps the CLI's own default.
const models: { value: string | null; label: string }[] = [
  { value: null, label: defaultModelLabel },
  { value: "opus", label: "Opus" },
  { value: "sonnet", label: "Sonnet" },
  { value: "haiku", label: "Haiku" },
];

function modelLabel(model: string | null): string {
  return models.find((m) => m.value === model)?.label ?? model ?? defaultModelLabel;
}

function entryOf(message: ChatMessage): Entry {
  if (message.role === "user") return { role: "user", text: message.content };
  const tools = message.tool_calls.map((tool, index) => ({
    callId: String(index),
    name: tool.name,
    arguments: tool.arguments,
    state: tool.is_error ? ("error" as const) : ("ok" as const),
  }));
  return { role: "assistant", text: message.content, tools, citations: message.citations, state: "done", error: null };
}

// A chat with one Mentor Group: a new Conversation (created with the first question) or an existing one.
// `group` is null when the Conversation's Group has been deleted, which leaves the Conversation read-only.
export function Chat({
  group,
  conversationId: openedId,
  claude,
  onClose,
  onChanged,
}: {
  group: MentorGroup | null;
  conversationId: number | null;
  claude: ClaudeCli | null;
  onClose: () => void;
  onChanged: (conversationId: number) => void;
}) {
  // Loaded once: later changes to the prop are this chat's own new Conversation, already on screen.
  const [initialId] = useState(openedId);
  const [conversationId, setConversationId] = useState(openedId);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState("");
  const [answering, setAnswering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One player at a time, under the answer it was opened from (by entry index).
  const player = usePlayer<number>();
  const list = useRef<HTMLOListElement>(null);
  const busy = useRef(false);
  // The Group's name as last seen, for when it is deleted while this chat is open.
  const lastGroupName = useRef(group?.name ?? "");
  if (group !== null) lastGroupName.current = group.name;

  useEffect(() => {
    if (initialId === null) return;
    let current = true;
    api
      .getConversation(initialId)
      .then((opened) => {
        if (!current) return;
        setDetail(opened);
        setModel(opened.model);
        setEntries(opened.messages.map(entryOf));
      })
      .catch((e: unknown) => current && setError(errorText(e)));
    return () => {
      current = false;
    };
  }, [initialId]);

  // Follows the answer as it streams.
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [entries]);

  const loading = initialId !== null && detail === null && error === null;
  // A Conversation that couldn't be loaded isn't continued blind.
  const loadFailed = initialId !== null && detail === null && error !== null;
  const groupName = group?.name ?? detail?.group_name ?? lastGroupName.current;
  const deleted = group === null || detail?.group_id === null;

  // Applies a change to the answer being streamed, the last entry.
  function updateAnswer(change: (answer: Answer) => Answer) {
    setEntries((current) => {
      const last = current.at(-1);
      return last?.role === "assistant" ? [...current.slice(0, -1), change(last)] : current;
    });
  }

  function apply(event: ChatStreamEvent) {
    switch (event.type) {
      case "text":
        return updateAnswer((a) => ({ ...a, text: a.text + event.text }));
      case "tool_call":
        return updateAnswer((a) => ({
          ...a,
          tools: [...a.tools, { callId: event.call_id, name: event.name, arguments: event.arguments, state: "running" }],
        }));
      case "tool_result":
        return updateAnswer((a) => ({
          ...a,
          tools: a.tools.map((t) =>
            t.callId === event.call_id ? { ...t, state: event.is_error ? "error" : "ok" } : t,
          ),
        }));
      case "done":
        return updateAnswer((a) => ({
          ...a,
          text: event.message.content,
          citations: event.message.citations,
          state: "done",
        }));
      case "error":
        return updateAnswer((a) => ({ ...a, state: "failed", error: event.message }));
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const question = draft.trim();
    // Enter submits the form even while Ask is disabled, and state updates land a render late, so a ref guards.
    if (busy.current || question === "" || group === null) return;
    busy.current = true;
    setError(null);
    setAnswering(true);
    let shown = false;
    let streamed = false;
    let id = conversationId;
    try {
      if (id === null) {
        id = (await api.createConversation(group.id, model)).id;
        setConversationId(id);
      }
      setEntries((current) => [
        ...current,
        { role: "user", text: question },
        { role: "assistant", text: "", tools: [], citations: [], state: "streaming", error: null },
      ]);
      shown = true;
      setDraft("");
      await api.sendMessage(id, question, (streamEvent) => {
        streamed = true;
        apply(streamEvent);
      });
      // A stream that closed without saying how the answer ended was cut off.
      updateAnswer((a) =>
        a.state === "streaming"
          ? { ...a, state: "failed", error: "The connection closed before the answer finished" }
          : a,
      );
    } catch (e) {
      if (streamed) {
        updateAnswer((a) => ({ ...a, state: "failed", error: errorText(e) }));
      } else {
        // The turn never started: take the question back out of the Conversation and return it to the box.
        if (shown) setEntries((current) => current.slice(0, -2));
        setDraft(question);
        setError(errorText(e));
      }
    } finally {
      busy.current = false;
      setAnswering(false);
      // Also after a failed turn: the Conversation exists and holds the question.
      if (id !== null) onChanged(id);
    }
  }

  return (
    <section aria-labelledby="chat-heading" className="rounded-md bg-panel px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="chat-heading" className={sectionHeadingClass}>
          Ask {groupName}
        </h2>
        <button className={quietButtonClass} type="button" onClick={onClose} disabled={answering}>
          Close
        </button>
      </div>
      {group === null || detail?.group_id === null ? (
        <p className={`mt-2 ${hintClass}`}>
          The Mentor Group {groupName} was deleted, so this Conversation can be read but not continued.
        </p>
      ) : (
        <p className={`mt-2 ${hintClass}`}>
          Answers come only from what {group.mentors.map((m) => m.name).join(", ") || "its Mentors"} said, with links to
          the moments they said it.
        </p>
      )}
      {!deleted && !loadFailed && claude !== null && claude.state !== "ready" && (
        <p role="alert" className={alertClass}>
          {claude.message ?? "The Claude CLI can't answer right now."}
        </p>
      )}
      {loading && <p className={`mt-4 ${hintClass}`}>Loading the Conversation…</p>}
      {entries.length > 0 && (
        <ol ref={list} className="mt-4 max-h-[36rem] space-y-4 overflow-y-auto" aria-label="Conversation">
          {entries.map((entry, index) => (
            <li key={index}>
              {entry.role === "user" ? (
                <Question text={entry.text} />
              ) : (
                <AnswerView
                  answer={entry}
                  player={player.playing?.where === index ? player.playing : null}
                  onPlay={(citation) => player.play(index, citation)}
                  onClosePlayer={player.close}
                />
              )}
            </li>
          ))}
        </ol>
      )}
      {error && (
        <p role="alert" className={alertClass}>
          {error}
        </p>
      )}
      {!deleted && !loading && !loadFailed && (
        <form onSubmit={ask} className="mt-4 space-y-2">
          <div className="flex flex-wrap gap-2">
            <textarea
              className={`${inputClass} min-h-[2.5rem] min-w-56 flex-1 resize-y`}
              rows={2}
              placeholder="e.g. What do they say about flattening a workbench top?"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
              aria-label="Question for the Mentor Group"
            />
            <button className={`${buttonClass} self-start`} type="submit" disabled={answering || !draft.trim()}>
              {answering ? "Answering…" : "Ask"}
            </button>
          </div>
          {conversationId === null ? (
            <label className="flex items-center gap-2 text-sm text-pencil">
              Model
              <select
                className={inputClass}
                value={model ?? ""}
                onChange={(e) => setModel(e.target.value === "" ? null : e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.label} value={m.value ?? ""}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className={hintClass}>Model: {modelLabel(model)}</p>
          )}
        </form>
      )}
    </section>
  );
}

function Question({ text }: { text: string }) {
  return (
    <p className="ml-auto w-fit max-w-[85%] rounded-md bg-machine/10 px-3 py-2 text-[15px] whitespace-pre-wrap">
      {text}
    </p>
  );
}

const toolLabels: Record<string, (args: Record<string, unknown>) => string> = {
  search: (args) => `Searched “${String(args.query ?? "")}”`,
  expand: (args) => `Read around Segment ${String(args.segment_id ?? "")}`,
  get_video: (args) => `Looked up Video ${String(args.video_id ?? "")}`,
  list_groups: () => "Listed the Group’s Mentors",
};

function toolLabel(tool: ToolActivity): string {
  return toolLabels[tool.name]?.(tool.arguments) ?? tool.name;
}

function AnswerView({
  answer,
  player,
  onPlay,
  onClosePlayer,
}: {
  answer: Answer;
  player: { citation: PlayerCitation; opening: number } | null;
  onPlay: (citation: Citation) => void;
  onClosePlayer: () => void;
}) {
  return (
    <div className="space-y-2">
      {answer.tools.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Tool calls">
          {answer.tools.map((tool) => (
            <li
              key={tool.callId}
              className={`rounded-full border px-2.5 py-0.5 text-[13px] ${
                tool.state === "error" ? "border-oxide/50 text-oxide" : "border-rule text-pencil"
              }`}
            >
              {toolLabel(tool)}
              {tool.state === "running" ? " …" : tool.state === "error" ? " (failed)" : ""}
            </li>
          ))}
        </ul>
      )}
      {answer.text !== "" && (
        <div className="text-[15px] leading-relaxed whitespace-pre-wrap">{renderMarkdown(answer.text, answer.citations, onPlay)}</div>
      )}
      {player !== null && <CitationPlayer {...player} onClose={onClosePlayer} />}
      {answer.state === "streaming" && answer.text === "" && answer.tools.length === 0 && (
        <p className={hintClass}>Thinking…</p>
      )}
      {answer.error && (
        <p role="alert" className={alertClass}>
          {answer.error}
        </p>
      )}
    </div>
  );
}

// Enough Markdown for grounded answers: links, bare URLs, bold, and inline code. Everything else shows as written. A
// bare URL leaves off sentence punctuation that follows it.
const inline = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s)]*[^\s).,;:!?])|\*\*([^*]+)\*\*|`([^`]+)`/g;

// The watch link forms the server reads Citations from (`chat.citation_links`), matched the same way.
const youtubeLink = /(?:https?:\/\/)?(?:(?:www\.|m\.)?youtube\.com\/watch\?([^\s)\]>"']+)|youtu\.be\/([\w-]+)(?:\?([^\s)\]>"']*))?)/;
const timestamp = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$/;

// The saved Citation a link points to, if any: links to Videos outside the Group, or made up, are plain links.
function citationOf(href: string, citations: Citation[]): Citation | undefined {
  const link = youtubeLink.exec(href);
  if (link === null) return undefined;
  const [, query, shortId, shortQuery] = link;
  const params = new URLSearchParams((query ?? shortQuery ?? "").replace(/[.,;:!?]+$/, "").replaceAll("&amp;", "&"));
  const videoId = shortId ?? params.get("v") ?? "";
  const time = timestamp.exec(params.get("t") ?? "");
  if (!/^[\w-]+$/.test(videoId) || time === null) return undefined;
  const [, hours, minutes, secs] = time;
  const seconds = Number(hours ?? 0) * 3600 + Number(minutes ?? 0) * 60 + Number(secs ?? 0);
  return citations.find((c) => c.youtube_video_id === videoId && c.seconds === seconds);
}

function renderMarkdown(text: string, citations: Citation[], onPlay: (citation: Citation) => void): ReactNode {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(inline)) {
    parts.push(text.slice(last, match.index));
    const [whole, label, labelled, bare, bold, code] = match;
    const key = match.index;
    const href = labelled ?? bare;
    if (href !== undefined) {
      const citation = citationOf(href, citations);
      parts.push(
        <a
          key={key}
          className="text-machine underline decoration-machine/40 underline-offset-2 hover:decoration-machine"
          href={href}
          target="_blank"
          rel="noreferrer"
          title={citation && "Plays here; Ctrl- or ⌘-click opens YouTube"}
          onClick={(e) => citation && playOnPlainClick(e, () => onPlay(citation))}
        >
          {label ?? bare}
        </a>,
      );
    } else if (bold !== undefined) {
      // Models often bold a cited claim, link included.
      parts.push(<strong key={key}>{renderMarkdown(bold, citations, onPlay)}</strong>);
    } else {
      parts.push(
        <code key={key} className="rounded-[2px] bg-ink/5 px-1 text-[14px]">
          {code}
        </code>,
      );
    }
    last = match.index + whole.length;
  }
  parts.push(text.slice(last));
  return parts;
}
