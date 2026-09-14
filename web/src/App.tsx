import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  api,
  errorText,
  type Channel,
  type Group,
  type Health,
  type Models,
  type Scope,
} from "@/lib/api";
import { useLiveUpdatesStopped, useServerEvents } from "@/lib/events";
import { useUrlState } from "@/lib/url-state";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ListColumn } from "@/shell/ListColumn";
import { MainHeader } from "@/shell/MainHeader";
import { ClaudeNotice, describeModel, ModelNotice, ServerNotice } from "@/shell/Notices";
import { Rail } from "@/shell/Rail";
import { Channels } from "./Channels";
import { Chat, type ChatScope } from "./Chat";
import { Conversations } from "./Conversations";
import { Groups } from "./Groups";
import { Search } from "./Search";
import { Syncs } from "./Syncs";
import { hintClass } from "./ui";

type HealthState = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error"; message: string };

const modelRoles = ["embedding", "reranker"] as const;
const modelLabels: Record<keyof Models, string> = { embedding: "embedding model", reranker: "reranking model" };

// The scope with its latest name and the Channels that answer; null once it is gone or the lists haven't loaded.
function resolveScope(scope: Scope | null, groups: Group[] | null, channels: Channel[] | null): ChatScope | null {
  if (scope === null) return null;
  if (scope.kind === "group") {
    const group = groups?.find((g) => g.id === scope.id);
    return group === undefined ? null : { ...scope, name: group.name, members: group.channels.map((c) => c.name) };
  }
  const channel = channels?.find((c) => c.id === scope.id);
  return channel === undefined ? null : { ...scope, name: channel.name, members: [channel.name] };
}

export function App() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [healthOpen, setHealthOpen] = useState(false);
  const { view, selection, setView, select } = useUrlState();
  // The open chat: a Group's or Channel's new Conversation, or a saved one (whose scope may be gone), with any
  // prefilled question. `opening` remounts the chat for each Ask or Open, but not when a new Conversation gets its id.
  const [chat, setChat] = useState<{
    scope: Scope | null;
    conversationId: number | null;
    draft: string;
    opening: number;
  } | null>(null);
  const [conversationsVersion, setConversationsVersion] = useState(0);
  // Shown with the scope's latest name and Channels; read-only once the Group or Channel is deleted.
  const chatScope = resolveScope(chat?.scope ?? null, groups, channels);

  const openings = useRef(0);
  const openChat = (scope: Scope | null, conversationId: number | null, draft = "") => {
    setChat({ scope, conversationId, draft, opening: ++openings.current });
    setView("chats");
    select({ conversation: conversationId ?? undefined });
  };
  const groupsLoaded = useCallback((loaded: Group[]) => {
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

  // Search's scopes, the Conversations filter, and a chat's scope name all need the lists, so they are loaded up
  // front instead of waiting for the Library view to mount its sections, which report their own load errors.
  useEffect(() => {
    void api.listChannels().then(setChannels, () => undefined);
    void api.listGroups().then(groupsLoaded, () => undefined);
  }, [groupsLoaded]);

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

  // ⌘K/Ctrl+K goes to Search and puts the cursor in the question. Search owns its own input, so it is found by the
  // label it already carries; ticket 05 replaces this with a ref.
  const [focusSearch, setFocusSearch] = useState(0);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      setView("search");
      setFocusSearch((n) => n + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setView]);
  useEffect(() => {
    if (focusSearch === 0) return;
    document.querySelector<HTMLInputElement>('input[aria-label="Question"]')?.focus();
  }, [focusSearch, view]);

  const openedChat = chat !== null &&
    groups !== null &&
    channels !== null &&
    (chatScope !== null || chat.conversationId !== null) && (
      <Chat
        key={chat.opening}
        scope={chatScope}
        conversationId={chat.conversationId}
        claude={state.kind === "ok" ? state.health.claude_cli : null}
        draft={chat.draft}
        onClose={() => {
          setChat(null);
          select({ conversation: undefined });
        }}
        onChanged={(conversationId) => {
          // A chat replaced mid-answer still finishes its turn; it mustn't retarget the chat now open.
          const opening = chat.opening;
          setChat((current) => (current?.opening === opening ? { ...current, conversationId } : current));
          select({ conversation: conversationId });
          setConversationsVersion((v) => v + 1);
        }}
      />
    );

  // Each section's list column and main pane. Library and Syncs get their real lists in tickets 04 and 05; for now
  // the old sections stay whole in the main pane and the column says where they are going.
  const placeholder = (text: string) => <p className={`mt-2 ${hintClass}`}>{text}</p>;
  const sections: Record<typeof view, { title: string; list: ReactNode; main: ReactNode }> = {
    chats: {
      title: "Chats",
      list: placeholder("Chats are filed here from ticket 04."),
      main: (
        <>
          {state.kind === "ok" && <ModelNotice models={state.health.models} />}
          {state.kind === "ok" && <ClaudeNotice claude={state.health.claude_cli} />}
          {openedChat}
          <Conversations
            groups={groups}
            channels={channels}
            version={conversationsVersion}
            openId={selection.conversation ?? null}
            onOpen={(conversation) =>
              // A deleted scope has no id left, so the Conversation opens read-only.
              openChat(
                conversation.scope.id === null ? null : { kind: conversation.scope.kind, id: conversation.scope.id },
                conversation.id,
              )
            }
            onDeleted={(conversationId) => {
              setChat((current) => (current?.conversationId === conversationId ? null : current));
              if (selection.conversation === conversationId) select({ conversation: undefined });
            }}
          />
        </>
      ),
    },
    search: {
      title: "Search",
      list: placeholder("The search form moves here in ticket 05."),
      main: <Search channels={channels} groups={groups} onAsk={(scope, draft) => openChat(scope, null, draft)} />,
    },
    library: {
      title: "Library",
      list: placeholder("Channels and Groups are listed here from ticket 03's Library phase."),
      main: (
        <>
          <Channels onLoaded={setChannels} />
          <Groups
            channels={channels}
            onLoaded={groupsLoaded}
            onAsk={(group) => openChat({ kind: "group", id: group.id }, null)}
          />
        </>
      ),
    },
    syncs: {
      title: "Syncs",
      list: placeholder("Syncs are listed here from ticket 03's Syncs phase."),
      main: <Syncs />,
    },
  };
  const section = sections[view];
  const listColumn = (
    <ListColumn title={section.title}>{section.list}</ListColumn>
  );

  return (
    <div className="flex h-screen">
      <Rail
        view={view}
        onView={setView}
        models={state.kind === "ok" ? state.health.models : null}
        claude={state.kind === "ok" ? state.health.claude_cli : null}
        onShowHealth={() => setHealthOpen(true)}
      />
      <div className="hidden h-full lg:flex">{listColumn}</div>
      <main className="flex min-w-0 flex-1 flex-col">
        <MainHeader title={section.title} list={{ title: section.title, content: listColumn }} />
        <div className="min-h-0 flex-1 overflow-y-auto pb-14 md:pb-0">
          <div className="mx-auto max-w-3xl space-y-8 px-6 py-5">
            <ServerNotice state={state} liveUpdatesStopped={liveUpdatesStopped} />
            {section.main}
          </div>
        </div>
      </main>
      {/* Tickets 04 and 05 mount the Sources Inspector here. */}
      <Dialog open={healthOpen} onOpenChange={setHealthOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Server health</DialogTitle>
          </DialogHeader>
          {state.kind === "ok" && (
            <dl className="grid gap-1 text-sm">
              <Fact term="Server" value={state.health.status} />
              <Fact term="sqlite-vec" value={state.health.database.sqlite_vec} />
              <Fact term="FTS5" value={state.health.database.fts5 ? "available" : "missing"} />
              {modelRoles.map((role) => (
                <Fact
                  key={role}
                  term={modelLabels[role]}
                  value={`${state.health.models[role].name} (${describeModel(state.health.models[role])})`}
                />
              ))}
              <Fact term="Claude CLI" value={state.health.claude_cli.state.replace("_", " ")} />
              <Fact term="Knowledge base" value={state.health.database.path} />
            </dl>
          )}
          {state.kind === "error" && <p className="text-sm text-destructive">Server unavailable: {state.message}</p>}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex min-w-0 gap-2">
      <dt className="text-muted-foreground first-letter:uppercase">{term}</dt>
      <dd className="min-w-0 truncate">{value}</dd>
    </div>
  );
}
