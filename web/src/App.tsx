import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { PanelRight } from "lucide-react";
import {
  api,
  errorText,
  type Channel,
  type Group,
  type Health,
  type Scope,
} from "@/lib/api";
import { useLiveUpdatesStopped, useServerEvents } from "@/lib/events";
import { useUrlState, type View } from "@/lib/url-state";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Inspector, useInspector } from "@/shell/Inspector";
import { ListColumn } from "@/shell/ListColumn";
import { MainHeader } from "@/shell/MainHeader";
import {
  ClaudeNotice,
  describeModel,
  modelLabels,
  modelRoles,
  ModelNotice,
  ServerNotice,
} from "@/shell/Notices";
import { Rail } from "@/shell/Rail";
import { Chat, type ChatScope } from "./Chat";
import { Conversations } from "./Conversations";
import { useLibraryDialogs } from "./library/Library";
import { LibraryList } from "./library/LibraryList";
import { LibraryMain } from "./library/LibraryMain";
import { Search } from "./Search";
import { SyncList } from "./syncs/SyncList";
import { SyncPage, SyncsEmpty } from "./syncs/SyncPage";
import { useSyncAll, useSyncs } from "./syncs/useSyncs";
import { Button } from "@/components/ui/button";

type HealthState = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error"; message: string };

// The views with a right column; the other two have nothing to inspect.
const inspected: Partial<Record<View, string>> = {
  chats: "Sources of the open chat appear here from ticket 04.",
  search: "Playing appears here from ticket 05.",
};

// ⌘K belongs to the app only when the user isn't typing into something or working inside a dialog.
function typingIn(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return true;
  return target.closest('[role="dialog"]') !== null;
}

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
  const inspector = useInspector();
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
  // A reload reopens the Conversation the URL names, in the scope it was held in; only what the URL carried at load.
  const [restoring] = useState(() => selection.conversation);
  useEffect(() => {
    if (restoring === undefined) return;
    const before = openings.current;
    void api.getConversation(restoring).then(
      (detail) => {
        // The user may have opened another chat while this was in flight; that one wins.
        if (openings.current !== before) return;
        setChat({
          scope: detail.scope.id === null ? null : { kind: detail.scope.kind, id: detail.scope.id },
          conversationId: restoring,
          draft: "",
          opening: ++openings.current,
        });
      },
      () => select({ conversation: undefined }),
    );
  }, [restoring, select]);

  const groupsLoaded = useCallback((loaded: Group[]) => {
    setGroups(loaded);
    // A deleted or renamed Group changes how its Conversations are listed.
    setConversationsVersion((v) => v + 1);
  }, []);
  // The newest model statuses from the event stream, and how many have arrived, so a Health response that was
  // already in flight can't undo them.
  const latestModels = useRef<Health["models"] | null>(null);
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

  // The server being unreachable is the notice, so it opens the Dialog that carries it.
  const serverError = state.kind === "error" ? state.message : null;
  useEffect(() => {
    if (serverError !== null) setHealthOpen(true);
  }, [serverError]);

  // Search's scopes, the Conversations filter, and a chat's scope name all need the lists, so they are loaded up
  // front instead of waiting for the Library view to mount its sections, which report their own load errors.
  const reloadChannels = useCallback(async () => {
    await api.listChannels().then(setChannels, () => undefined);
  }, []);
  const reloadGroups = useCallback(async () => {
    await api.listGroups().then(groupsLoaded, () => undefined);
  }, [groupsLoaded]);
  useEffect(() => {
    void reloadChannels();
    void reloadGroups();
  }, [reloadChannels, reloadGroups]);

  // Channel counts follow Syncs and Video changes, at most one reload a second while they stream in, so they stay
  // fresh whichever view is open.
  const countsTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(countsTimer.current), []);
  useServerEvents((event) => {
    if (event.type !== "sync" && event.type !== "videos" && event.type !== "ready") return;
    if (countsTimer.current !== undefined) return;
    countsTimer.current = window.setTimeout(() => {
      countsTimer.current = undefined;
      void reloadChannels();
    }, 1000);
  });

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
  const { items: syncs, error: syncsError } = useSyncs();
  const syncAll = useSyncAll();
  const library = useLibraryDialogs({ select, reloadChannels, reloadGroups });

  // ⌘K/Ctrl+K goes to Search and puts the cursor in the question. Search owns its own input, so it is found by the
  // label it already carries; ticket 05 replaces this with a ref.
  const [focusSearch, setFocusSearch] = useState(0);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey)) return;
      if (typingIn(event.target)) return;
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

  // Each section's list column and main pane. Library and Syncs have their real lists; Chats and Search keep the v1
  // sections in the main pane until tickets 04 and 05 move them.
  const placeholder = (text: string) => <p className="mt-2 text-sm text-muted-foreground">{text}</p>;
  const sections: Record<typeof view, { title: string; actions?: ReactNode; list: ReactNode; main: ReactNode }> = {
    chats: {
      title: "Chats",
      list: placeholder("Chats are filed here from ticket 04."),
      main: (
        <>
          {state.kind === "ok" && !liveUpdatesStopped && <ModelNotice models={state.health.models} />}
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
      list: (
        <LibraryList
          channels={channels}
          groups={groups}
          selection={selection}
          select={select}
          onAddChannel={library.addChannel}
          onNewGroup={library.newGroup}
        />
      ),
      main: (
        <>
          <LibraryMain
            channels={channels}
            groups={groups}
            syncs={syncs}
            selection={selection}
            select={select}
            reloadChannels={reloadChannels}
            reloadGroups={reloadGroups}
            onNewChat={(scope) => openChat(scope, null)}
          />
          {library.dialogs}
        </>
      ),
    },
    syncs: {
      title: "Syncs",
      actions: (
        <Button variant="ghost" size="sm" disabled={syncAll.starting} onClick={() => void syncAll.run()}>
          Sync all
        </Button>
      ),
      list: (
        <SyncList
          syncs={syncs}
          error={syncsError}
          selection={selection}
          select={select}
          syncAllError={syncAll.error}
        />
      ),
      main:
        selection.sync === undefined ? <SyncsEmpty /> : <SyncPage syncId={selection.sync} syncs={syncs} />,
    },
  };
  const section = sections[view];
  const listColumn = (
    <ListColumn title={section.title} actions={section.actions}>
      {section.list}
    </ListColumn>
  );
  const inspectorBody = inspected[view];

  return (
    <div className="flex h-screen">
      <Rail
        view={view}
        onView={setView}
        syncs={syncs}
        models={state.kind === "ok" ? state.health.models : null}
        claude={state.kind === "ok" ? state.health.claude_cli : null}
        serverError={serverError}
        onShowHealth={() => setHealthOpen(true)}
      />
      <div className="hidden h-full lg:flex">{listColumn}</div>
      <main className="flex min-w-0 flex-1 flex-col">
        <MainHeader
          title={section.title}
          list={{ key: `${view}:${JSON.stringify(selection)}`, title: section.title, content: listColumn }}
          right={
            inspectorBody !== undefined && (
              <Button
                variant="ghost"
                size="icon"
                aria-label={inspector.open ? "Hide sources" : "Show sources"}
                aria-pressed={inspector.open}
                onClick={inspector.toggle}
              >
                <PanelRight />
              </Button>
            )
          }
        />
        <div className="min-h-0 flex-1 overflow-y-auto pb-14 md:pb-0">
          <div className="mx-auto max-w-3xl space-y-8 px-6 py-5">
            <ServerNotice state={state} liveUpdatesStopped={liveUpdatesStopped} />
            {section.main}
          </div>
        </div>
      </main>
      {inspectorBody !== undefined && inspector.open && (
        <Inspector title="Sources" onHide={inspector.hide}>
          <p className="text-sm text-muted-foreground">{inspectorBody}</p>
        </Inspector>
      )}
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
              {modelRoles.map((role) => {
                const status = state.health.models[role];
                // The failure is what the user needs; the model's name only says which one failed.
                const value =
                  status.state === "failed" && status.error !== null
                    ? `${status.name} — ${status.error}`
                    : `${status.name} (${describeModel(status)})`;
                return <Fact key={role} term={modelLabels[role]} value={value} />;
              })}
              <Fact
                term="Claude CLI"
                value={
                  state.health.claude_cli.state === "ready"
                    ? "ready"
                    : (state.health.claude_cli.message ?? state.health.claude_cli.state.replace("_", " "))
                }
              />
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
