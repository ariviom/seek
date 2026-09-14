import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText, type Health, type Mentor, type MentorGroup, type Models, type ModelStatus } from "./api";
import { Chat } from "./Chat";
import { Conversations } from "./Conversations";
import { useLiveUpdatesStopped, useServerEvents } from "./events";
import { Groups } from "./Groups";
import { Mentors } from "./Mentors";
import { Search } from "./Search";
import { Syncs } from "./Syncs";
import { hintClass } from "./ui";

type HealthState = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error"; message: string };

const modelRoles = ["embedding", "reranker"] as const;
const modelLabels: Record<keyof Models, string> = { embedding: "embedding model", reranker: "reranking model" };
// What can't run until each model is ready.
const modelWaiters: Record<keyof Models, string> = { embedding: "Search and Syncs wait", reranker: "Search waits" };

function megabytes(bytes: number): string {
  return String(Math.floor(bytes / 1_000_000));
}

function describeModel(status: ModelStatus): string {
  switch (status.state) {
    case "downloading":
      return status.total_bytes === null
        ? `downloading, ${megabytes(status.downloaded_bytes ?? 0)} MB`
        : `downloading, ${megabytes(status.downloaded_bytes ?? 0)} of ${megabytes(status.total_bytes)} MB`;
    default:
      return status.state;
  }
}

function ModelNotice({ models }: { models: Models }) {
  const role = modelRoles.find((r) => models[r].state !== "ready");
  if (role === undefined) return null;
  const status = models[role];
  if (status.state === "failed") {
    // The server's message names the model and says what to do.
    return (
      <p role="alert" className="text-sm text-oxide">
        {status.error ?? `The ${modelLabels[role]} failed to load`}
      </p>
    );
  }
  return (
    <p role="status" className={hintClass}>
      The {modelLabels[role]} is {describeModel(status)}. {modelWaiters[role]} until it’s ready.
    </p>
  );
}

export function App() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const [mentors, setMentors] = useState<Mentor[] | null>(null);
  const [groups, setGroups] = useState<MentorGroup[] | null>(null);
  // The open chat: a Group's new Conversation, or a saved one (whose Group may be gone). `opening` remounts the chat
  // for each Ask or Open, but not when a new Conversation gets its id.
  const [chat, setChat] = useState<{ groupId: number | null; conversationId: number | null; opening: number } | null>(
    null,
  );
  const [conversationsVersion, setConversationsVersion] = useState(0);
  // Shown with the Group's latest name and Mentors; read-only once the Group is deleted.
  const chatGroup = groups?.find((g) => g.id === chat?.groupId) ?? null;

  const openings = useRef(0);
  const openChat = (groupId: number | null, conversationId: number | null) => {
    setChat({ groupId, conversationId, opening: ++openings.current });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const groupsLoaded = useCallback((loaded: MentorGroup[]) => {
    setGroups(loaded);
    // A deleted or renamed Group changes how its Conversations are listed.
    setConversationsVersion((v) => v + 1);
  }, []);
  // The newest model statuses from the event stream, and how many have arrived, so a Health response that was
  // already in flight can't undo them.
  const latestModels = useRef<Models | null>(null);
  const modelEvents = useRef(0);

  const loadHealth = useCallback(async () => {
    const eventsBefore = modelEvents.current;
    try {
      const health = await api.health();
      const models = modelEvents.current !== eventsBefore && latestModels.current ? latestModels.current : health.models;
      setState({ kind: "ok", health: { ...health, models } });
    } catch (error) {
      setState({ kind: "error", message: errorText(error) });
    }
  }, []);

  useEffect(() => {
    void loadHealth();
  }, [loadHealth]);

  useServerEvents((event) => {
    // Models may have progressed while the stream was down.
    if (event.type === "ready") void loadHealth();
    if (event.type === "models") {
      latestModels.current = event.models;
      modelEvents.current += 1;
      setState((current) =>
        current.kind === "ok" ? { kind: "ok", health: { ...current.health, models: event.models } } : current,
      );
    }
  });

  const liveUpdatesStopped = useLiveUpdatesStopped();

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-panel">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-3 sm:px-8">
          <h1 className="font-condensed text-3xl leading-none font-semibold">mentor</h1>
          {state.kind === "error" && (
            <p role="alert" className="text-sm text-oxide">
              Server unavailable: {state.message}
            </p>
          )}
          {state.kind !== "error" && liveUpdatesStopped && (
            <p role="alert" className="text-sm text-oxide">
              Live updates stopped. Reload the page, and sign in again if asked.
            </p>
          )}
          {state.kind === "ok" && !liveUpdatesStopped && <ModelNotice models={state.health.models} />}
        </div>
      </header>
      <div className="mx-auto grid max-w-6xl gap-x-10 gap-y-12 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <main className="min-w-0 space-y-12">
          {/* A new chat whose Group was deleted before its first question just closes. */}
          {chat !== null && groups !== null && (chatGroup !== null || chat.conversationId !== null) && (
            <Chat
              key={chat.opening}
              group={chatGroup}
              conversationId={chat.conversationId}
              claude={state.kind === "ok" ? state.health.claude_cli : null}
              onClose={() => setChat(null)}
              onChanged={(conversationId) => {
                // A chat replaced mid-answer still finishes its turn; it mustn't retarget the chat now open.
                const opening = chat.opening;
                setChat((current) => (current?.opening === opening ? { ...current, conversationId } : current));
                setConversationsVersion((v) => v + 1);
              }}
            />
          )}
          <Search mentors={mentors} groups={groups} />
          <Mentors onLoaded={setMentors} />
          <Groups mentors={mentors} onLoaded={groupsLoaded} onAsk={(group) => openChat(group.id, null)} />
          <Conversations
            groups={groups}
            version={conversationsVersion}
            openId={chat?.conversationId ?? null}
            onOpen={(conversation) => openChat(conversation.group_id, conversation.id)}
          />
        </main>
        <aside className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto">
          <Syncs />
        </aside>
      </div>
      <footer className="mx-auto max-w-6xl px-5 pb-8 sm:px-8">
        {state.kind === "ok" && (
          <dl className="flex flex-wrap gap-x-6 gap-y-1 border-t border-rule pt-3 text-[13px] text-pencil">
            <div className="flex gap-1.5">
              <dt>Server</dt>
              <dd className="text-ink">{state.health.status}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt>sqlite-vec</dt>
              <dd className="text-ink">{state.health.database.sqlite_vec}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt>FTS5</dt>
              <dd className="text-ink">{state.health.database.fts5 ? "available" : "missing"}</dd>
            </div>
            {modelRoles.map((role) => (
              <div key={role} className="flex min-w-0 gap-1.5">
                <dt className="first-letter:uppercase">{modelLabels[role]}</dt>
                <dd className="truncate text-ink" title={state.health.models[role].error ?? undefined}>
                  {state.health.models[role].name} ({describeModel(state.health.models[role])})
                </dd>
              </div>
            ))}
            <div className="flex min-w-0 gap-1.5">
              <dt>Claude CLI</dt>
              <dd
                className={`truncate ${state.health.claude_cli.state === "ready" ? "text-ink" : "text-oxide"}`}
                title={state.health.claude_cli.message ?? state.health.claude_cli.cli_path ?? undefined}
              >
                {state.health.claude_cli.state.replace("_", " ")}
              </dd>
            </div>
            <div className="flex min-w-0 gap-1.5">
              <dt>Knowledge base</dt>
              <dd className="truncate text-ink">{state.health.database.path}</dd>
            </div>
          </dl>
        )}
      </footer>
    </div>
  );
}
