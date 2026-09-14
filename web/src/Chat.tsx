import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, errorText, type ChatStreamEvent, type MentorGroup } from "./api";
import { alertClass, buttonClass, hintClass, inputClass, quietButtonClass, sectionHeadingClass } from "./ui";

type ToolActivity = { callId: string; name: string; arguments: Record<string, unknown>; state: "running" | "ok" | "error" };
type Entry =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      text: string;
      tools: ToolActivity[];
      state: "streaming" | "done" | "failed";
      error: string | null;
    };
type Answer = Extract<Entry, { role: "assistant" }>;

// A chat with one Mentor Group. The Conversation is created with the first question.
export function Chat({ group, onClose }: { group: MentorGroup; onClose: () => void }) {
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState("");
  const [answering, setAnswering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const list = useRef<HTMLOListElement>(null);
  const busy = useRef(false);

  // Follows the answer as it streams.
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [entries]);

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
          tools: a.tools.map((t) => (t.callId === event.call_id ? { ...t, state: event.is_error ? "error" : "ok" } : t)),
        }));
      case "done":
        return updateAnswer((a) => ({ ...a, text: event.message.content, state: "done" }));
      case "error":
        return updateAnswer((a) => ({ ...a, state: "failed", error: event.message }));
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const question = draft.trim();
    // Enter submits the form even while Ask is disabled, and state updates land a render late, so a ref guards.
    if (busy.current || question === "") return;
    busy.current = true;
    setError(null);
    setAnswering(true);
    let shown = false;
    let streamed = false;
    try {
      const id = conversationId ?? (await api.createConversation(group.id, null)).id;
      setConversationId(id);
      setEntries((current) => [
        ...current,
        { role: "user", text: question },
        { role: "assistant", text: "", tools: [], state: "streaming", error: null },
      ]);
      shown = true;
      setDraft("");
      await api.sendMessage(id, question, (streamEvent) => {
        streamed = true;
        apply(streamEvent);
      });
      // A stream that closed without saying how the answer ended was cut off.
      updateAnswer((a) =>
        a.state === "streaming" ? { ...a, state: "failed", error: "The connection closed before the answer finished" } : a,
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
    }
  }

  return (
    <section aria-labelledby="chat-heading" className="rounded-md bg-panel px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="chat-heading" className={sectionHeadingClass}>
          Ask {group.name}
        </h2>
        <button className={quietButtonClass} type="button" onClick={onClose} disabled={answering}>
          Close
        </button>
      </div>
      <p className={`mt-2 ${hintClass}`}>
        Answers come only from what {group.mentors.map((m) => m.name).join(", ") || "its Mentors"} said, with links to
        the moments they said it.
      </p>
      {entries.length > 0 && (
        <ol ref={list} className="mt-4 max-h-[36rem] space-y-4 overflow-y-auto" aria-label="Conversation">
          {entries.map((entry, index) => (
            <li key={index}>{entry.role === "user" ? <Question text={entry.text} /> : <AnswerView answer={entry} />}</li>
          ))}
        </ol>
      )}
      {error && (
        <p role="alert" className={alertClass}>
          {error}
        </p>
      )}
      <form onSubmit={ask} className="mt-4 flex flex-wrap gap-2">
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
      </form>
    </section>
  );
}

function Question({ text }: { text: string }) {
  return <p className="ml-auto w-fit max-w-[85%] rounded-md bg-machine/10 px-3 py-2 text-[15px] whitespace-pre-wrap">{text}</p>;
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

function AnswerView({ answer }: { answer: Answer }) {
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
      {answer.text !== "" && <div className="text-[15px] leading-relaxed whitespace-pre-wrap">{renderMarkdown(answer.text)}</div>}
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

// Enough Markdown for grounded answers: links (the Citations), bare URLs, bold, and inline code. Everything else shows
// as written.
// A bare URL leaves off sentence punctuation that follows it.
const inline = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s)]*[^\s).,;:!?])|\*\*([^*]+)\*\*|`([^`]+)`/g;

function renderMarkdown(text: string): ReactNode {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(inline)) {
    parts.push(text.slice(last, match.index));
    const [whole, label, labelled, bare, bold, code] = match;
    const key = match.index;
    if (labelled !== undefined || bare !== undefined) {
      parts.push(
        <a
          key={key}
          className="text-machine underline decoration-machine/40 underline-offset-2 hover:decoration-machine"
          href={labelled ?? bare}
          target="_blank"
          rel="noreferrer"
        >
          {label ?? bare}
        </a>,
      );
    } else if (bold !== undefined) {
      parts.push(<strong key={key}>{bold}</strong>);
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
