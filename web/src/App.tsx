import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { PanelRight } from "lucide-react";
import {
  api,
  errorText,
  type Channel,
  type Citation,
  type Group,
  type Health,
  type Scope,
  type Settings,
} from "@/lib/api";
import { useLiveUpdatesStopped, useServerEvents } from "@/lib/events";
import { useMediaQuery } from "@/lib/media";
import { usePlayback } from "@/lib/playback";
import { channelSync } from "@/lib/sync-status";
import { useUrlState, type View } from "@/lib/url-state";
import { ThumbnailsToggle } from "@/components/Frames";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Inspector, useInspector } from "@/shell/Inspector";
import { ListColumn } from "@/shell/ListColumn";
import { MainHeader } from "@/shell/MainHeader";
import {
  describeEngine,
  describeModel,
  EngineNotice,
  engineLabels,
  engineNames,
  modelLabels,
  modelRoles,
  ModelNotice,
  ServerNotice,
} from "@/shell/Notices";
import { Rail } from "@/shell/Rail";
import { conversationModel } from "@/lib/models";
import { SettingsView } from "./settings/SettingsView";
import { ConversationView } from "./chats/ConversationView";
import { Folders, NewChatMenu, useConversations } from "./chats/Folders";
import { Lightbox } from "./chats/Lightbox";
import { PlayerCard } from "./chats/PlayerCard";
import { liveScope } from "./chats/scope";
import { Sources, sourcesOf } from "./chats/Sources";
import { useLibraryDialogs } from "./library/Library";
import { LibraryList } from "./library/LibraryList";
import { LibraryMain } from "./library/LibraryMain";
import { SearchForm } from "./search/SearchForm";
import { SearchResults } from "./search/SearchResults";
import { useSearch } from "./search/useSearch";
import { SyncList } from "./syncs/SyncList";
import { SyncPage, SyncsEmpty } from "./syncs/SyncPage";
import { useSyncAll, useSyncs } from "./syncs/useSyncs";
import { Button } from "@/components/ui/button";

type HealthState = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error"; message: string };

// The views with a right column, by its title; the other two have nothing to inspect.
const inspected: Partial<Record<View, string>> = { chats: "Sources", search: "Playing" };

// ⌘K belongs to the app only when the user isn't typing into something or working inside a dialog.
function typingIn(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return true;
  return target.closest('[role="dialog"]') !== null;
}

export function App() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [healthOpen, setHealthOpen] = useState(false);
  const { view, selection, setView, select } = useUrlState();
  const inspector = useInspector();
  const playback = usePlayback(inspector.open);
  // Below 1024px the list column lives only in the header's Sheet, so it is never mounted twice.
  const wide = useMediaQuery("(min-width: 1024px)");
  // The open chat is the Conversation the URL names, or else a new one in `scope` with any prefilled question.
  // `opening` remounts the chat for each one opened, but not when a new Conversation gets its id.
  const [chat, setChat] = useState<{ scope: Scope | null; draft: string; opening: number }>({
    scope: null,
    draft: "",
    opening: 0,
  });
  const [chatCitations, setChatCitations] = useState<Citation[]>([]);
  const [conversationsVersion, setConversationsVersion] = useState(0);
  const conversations = useConversations(conversationsVersion);

  const openings = useRef(0);
  // Counts choices made in the list column, so the Sheet that holds it below 1024px closes even when nothing changed.
  const [listChoices, setListChoices] = useState(0);
  const openConversation = (conversationId: number) => {
    setListChoices((n) => n + 1);
    if (conversationId === selection.conversation) return;
    setChat({ scope: null, draft: "", opening: ++openings.current });
    playback.close();
    select({ conversation: conversationId });
  };
  const newChat = (scope: Scope, draft = "") => {
    setChat({ scope, draft, opening: ++openings.current });
    playback.close();
    setView("chats");
    select({ conversation: undefined });
  };
  const closeChat = () => {
    playback.close();
    setChat({ scope: null, draft: "", opening: ++openings.current });
    select({ conversation: undefined });
  };

  const groupsLoaded = useCallback((loaded: Group[]) => {
    setGroups(loaded);
    // A deleted or renamed Group changes how its Conversations are listed.
    setConversationsVersion((v) => v + 1);
  }, []);
  // Likewise a renamed or removed Channel; the list reloads with every Sync's counts, so only its names are watched.
  const channelNames = channels?.map((c) => `${c.id}:${c.name}`).join("\n");
  const seenChannelNames = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (seenChannelNames.current !== undefined && channelNames !== seenChannelNames.current) {
      setConversationsVersion((v) => v + 1);
    }
    seenChannelNames.current = channelNames;
  }, [channelNames]);
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

  // The preferences the chats follow: which model an unpinned Conversation runs, and what the settings screen edits.
  // A failure is kept, not swallowed: nothing may claim a default it hasn't read.
  const [settings, setSettings] = useState<Settings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const loadSettings = useCallback(async () => {
    try {
      setSettings(await api.settings());
      setSettingsError(null);
    } catch (error) {
      setSettingsError(errorText(error));
    }
  }, []);
  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

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
    // Models may have progressed while the stream was down, and a key or preference saved since changes who
    // answers, so the composer follows without a reload.
    // A preference saved in another tab changes who answers and which model the chats here follow.
    if (event.type === "ready" || event.type === "settings" || event.type === "credentials") {
      void loadHealth();
      if (event.type !== "credentials") void loadSettings();
    }
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
  // Sync all is a no-op once every active Channel already has a Sync queued or running.
  const active = channels?.filter((channel) => channel.indexed) ?? [];
  const syncing = active.length > 0 && active.every((channel) => channelSync(syncs, channel.id) !== null);
  const library = useLibraryDialogs({ select, reloadChannels, reloadGroups });

  const search = useSearch(channels, groups);

  const closePlayback = playback.close;
  // Leaving a section stops what it was playing.
  const changeView = useCallback(
    (next: View) => {
      if (next !== view) closePlayback();
      setView(next);
    },
    [view, closePlayback, setView],
  );

  // ⌘K/Ctrl+K goes to Search and puts the cursor in the question.
  const [focusSearch, setFocusSearch] = useState(0);
  const clearFocusSearch = useCallback(() => setFocusSearch(0), []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey)) return;
      if (typingIn(event.target)) return;
      event.preventDefault();
      changeView("search");
      setFocusSearch((n) => n + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [changeView]);

  const health = state.kind === "ok" ? state.health : null;
  const chatOpen = selection.conversation !== undefined || chat.scope !== null;
  const summary = conversations.items?.find((c) => c.id === selection.conversation);
  const chatScopeName =
    chat.scope !== null ? (liveScope(chat.scope, groups, channels)?.name ?? "") : (summary?.scope.name ?? "");
  const sources = sourcesOf(chatCitations);

  // Each section's list column and main pane.
  // Settings has no list of its own, so its column is left out rather than shown empty.
  const sections: Record<
    typeof view,
    { title: string; header?: ReactNode; actions?: ReactNode; list?: ReactNode; main: ReactNode }
  > = {
    chats: {
      title: "Chats",
      header: chatOpen && (
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate font-normal text-muted-foreground">{chatScopeName}</span>
          <span className="text-muted-foreground/60">/</span>
          <span className="truncate">{chat.scope !== null ? "New chat" : summary?.title}</span>
          {summary !== undefined && (
            <Badge variant="outline" className="font-normal text-muted-foreground">
              {conversationModel(summary.model, settings?.model ?? null, health?.chat.active ?? null)}
            </Badge>
          )}
        </span>
      ),
      actions: <NewChatMenu groups={groups} channels={channels} onNewChat={newChat} />,
      list: (
        <Folders
          conversations={conversations.items}
          error={conversations.error}
          groups={groups}
          channels={channels}
          selectedId={selection.conversation ?? null}
          reload={conversations.reload}
          onOpen={openConversation}
          onNewChat={newChat}
          onDeleted={(conversationId) => {
            if (selection.conversation === conversationId) closeChat();
          }}
        />
      ),
      main: chatOpen ? (
        <ConversationView
          key={chat.opening}
          conversationId={selection.conversation ?? null}
          scope={chat.scope}
          draft={chat.draft}
          groups={groups}
          channels={channels}
          syncs={syncs}
          chat={health?.chat ?? null}
          defaultChoice={settings?.model ?? null}
          usage={summary?.usage ?? null}
          playback={playback}
          notices={
            health !== null && (
              <>
                {!liveUpdatesStopped && <ModelNotice models={health.models} />}
                <EngineNotice chat={health.chat} onOpenSettings={() => changeView("settings")} />
              </>
            )
          }
          onChanged={(conversationId) => {
            // A chat replaced mid-answer still finishes its turn; it mustn't retarget the chat now open.
            if (chat.opening === openings.current) select({ conversation: conversationId });
            void conversations.reload();
          }}
          onCitations={setChatCitations}
          onEditGroup={(groupId) => {
            changeView("library");
            select({ group: groupId, channel: undefined, tab: "groups" });
          }}
          onOpenSettings={() => changeView("settings")}
        />
      ) : (
        <div className="mx-auto max-w-3xl px-6 py-6">
          <p className="text-sm text-muted-foreground">
            {conversations.items?.length === 0
              ? "No chats yet. Start one with + on a group or channel, or from its page in the Library."
              : "Pick a chat, or start a new one with + on a group or channel."}
          </p>
        </div>
      ),
    },
    search: {
      title: "Search",
      list: (
        <SearchForm
          search={search}
          channels={channels}
          groups={groups}
          focusRequest={focusSearch}
          onFocused={clearFocusSearch}
          onSearch={() => {
            // A new search replaces the results the player was opened from.
            playback.close();
            setListChoices((n) => n + 1);
          }}
        />
      ),
      main: (
        <>
          {health !== null && !liveUpdatesStopped && <ModelNotice models={health.models} />}
          <SearchResults
            search={search}
            groups={groups}
            thumbnails={settings?.thumbnails ?? true}
            playback={playback}
            onAsk={newChat}
          />
        </>
      ),
    },
    library: {
      title: "Library",
      list: (
        <LibraryList
          channels={channels}
          groups={groups}
          syncs={syncs}
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
            onNewChat={newChat}
            onOpenSync={(syncId) => {
              changeView("syncs");
              select({ sync: syncId });
            }}
          />
          {library.dialogs}
        </>
      ),
    },
    syncs: {
      title: "Syncs",
      actions: (
        <Button
          variant="ghost"
          size="sm"
          disabled={syncAll.starting || syncing}
          onClick={() => void syncAll.run()}
        >
          {syncing ? "Syncing…" : "Sync all"}
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
    settings: {
      title: "Settings",
      main: (
        <SettingsView
          health={health}
          settings={settings}
          settingsError={settingsError}
          onSettings={setSettings}
        />
      ),
    },
  };
  const section = sections[view];
  const listColumn =
    section.list === undefined ? undefined : (
      <ListColumn title={section.title} actions={section.actions}>
        {section.list}
      </ListColumn>
    );
  const inspectorTitle = inspected[view];

  return (
    <div className="flex h-screen">
      <Rail
        view={view}
        onView={changeView}
        syncs={syncs}
        models={state.kind === "ok" ? state.health.models : null}
        chat={state.kind === "ok" ? state.health.chat : null}
        serverError={serverError}
        onShowHealth={() => setHealthOpen(true)}
      />
      {wide && listColumn !== undefined && <div className="flex h-full">{listColumn}</div>}
      <main className="flex min-w-0 flex-1 flex-col">
        <MainHeader
          title={section.header || section.title}
          list={
            wide || listColumn === undefined
              ? undefined
              : {
                  key: `${view}:${JSON.stringify(selection)}:${chat.opening}:${listChoices}`,
                  title: section.title,
                  content: listColumn,
                }
          }
          right={
            inspectorTitle !== undefined && (
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground"
                aria-label={inspector.open ? `Hide ${inspectorTitle.toLowerCase()}` : `Show ${inspectorTitle.toLowerCase()}`}
                aria-pressed={inspector.open}
                onClick={() => {
                  // With no panel the card is gone, so what it was playing stops unless it is playing large.
                  if (inspector.open && !playback.large) playback.close();
                  inspector.toggle();
                }}
              >
                <PanelRight /> {inspectorTitle}
              </Button>
            )
          }
        />
        {/* Chats fills the pane itself, so its composer stays at the bottom. It stays mounted while another section
            shows, so an answer keeps streaming into it and its draft survives. */}
        <div className={`min-h-0 flex-1 flex-col pb-14 md:pb-0 ${view === "chats" ? "flex" : "hidden"}`}>
          {(state.kind === "error" || liveUpdatesStopped) && (
            <div className="mx-auto w-full max-w-3xl px-6 pt-5">
              <ServerNotice state={state} liveUpdatesStopped={liveUpdatesStopped} />
            </div>
          )}
          {sections.chats.main}
        </div>
        {view !== "chats" && (
          <div className="min-h-0 flex-1 overflow-y-auto pb-14 md:pb-0">
            <div className="mx-auto max-w-3xl space-y-8 px-6 py-5">
              <ServerNotice state={state} liveUpdatesStopped={liveUpdatesStopped} />
              {section.main}
            </div>
          </div>
        )}
      </main>
      {inspectorTitle !== undefined && inspector.open && (
        <Inspector
          title={inspectorTitle}
          count={view === "chats" && chatOpen ? sources.reduce((n, group) => n + group.citations.length, 0) : undefined}
          actions={
            view === "chats" && chatOpen ? (
              <ThumbnailsToggle settings={settings} onSettings={setSettings} />
            ) : undefined
          }
          onHide={() => {
            if (!playback.large) playback.close();
            inspector.hide();
          }}
        >
          <PlayerCard
            controls={playback}
            empty={
              view === "chats"
                ? "Pick a source, or a link in an answer, and it plays here."
                : "Play a result and it plays here."
            }
          />
          {view === "chats" && chatOpen && (
            <Sources
              citations={chatCitations}
              thumbnails={settings?.thumbnails ?? true}
              playingKey={playback.playingKey}
              onPlay={playback.play}
            />
          )}
        </Inspector>
      )}
      <Lightbox controls={playback} />
      <Dialog open={healthOpen} onOpenChange={setHealthOpen}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
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
                    ? `${status.name} (${describeModel(status)}): ${status.error}`
                    : `${status.name} (${describeModel(status)})`;
                return <Fact key={role} term={modelLabels[role]} value={value} wrap />;
              })}
              <Fact
                term="Chat engine"
                value={
                  state.health.chat.active === null
                    ? "none available"
                    : engineLabels[state.health.chat.active]
                }
              />
              {engineNames.map((name) => (
                <Fact key={name} term={engineLabels[name]} value={describeEngine(state.health.chat.engines[name])} wrap />
              ))}
              <Fact term="Knowledge base" value={state.health.database.path} />
            </dl>
          )}
          {state.kind === "error" && <p className="text-sm text-destructive">Server unavailable: {state.message}</p>}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Fact({ term, value, wrap = false }: { term: string; value: string; wrap?: boolean }) {
  return (
    <div className="flex min-w-0 gap-2">
      <dt className="max-w-[35%] shrink-0 text-muted-foreground first-letter:uppercase">{term}</dt>
      <dd className={wrap ? "min-w-0 break-words" : "min-w-0 truncate"}>{value}</dd>
    </div>
  );
}
