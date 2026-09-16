import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  api,
  errorText,
  type Channel,
  type ChatStreamEvent,
  type Citation,
  type ConversationDetail,
  type Group,
  type Scope,
  type Sync,
} from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import type { PlaybackControls } from "@/lib/playback";
import { channelSync, syncingNote } from "@/lib/sync-status";
import { Composer } from "./Composer";
import { NewChat } from "./NewChat";
import { ScopeChip } from "./ScopeChip";
import { liveScope } from "./scope";
import { consultedVideos, entryOf, Transcript, type Answer, type Entry } from "./Transcript";

// A chat with one Group or Channel: a new Conversation in `scope` (created with the first question), or the saved one
// `conversationId` names, whose scope comes with it and may since have been deleted, leaving it read-only. `draft`
// prefills the question. Remounted for each chat opened, but not when a new Conversation gets its id.
export function ConversationView({
  conversationId: openedId,
  scope: newScope,
  draft: initialDraft,
  groups,
  channels,
  syncs,
  playback,
  notices,
  onChanged,
  onCitations,
  onEditGroup,
}: {
  conversationId: number | null;
  scope: Scope | null;
  draft: string;
  groups: Group[] | null;
  channels: Channel[] | null;
  syncs: Sync[] | null;
  playback: PlaybackControls;
  notices: ReactNode;
  // After each turn, also a failed one: the Conversation exists and holds the question.
  onChanged: (conversationId: number) => void;
  onCitations: (citations: Citation[]) => void;
  onEditGroup: (groupId: number) => void;
}) {
  // Loaded once: later changes to the prop are this chat's own new Conversation, already on screen.
  const [initialId] = useState(openedId);
  const [conversationId, setConversationId] = useState(openedId);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [webAccess, setWebAccess] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState(initialDraft);
  const [answering, setAnswering] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const questionBox = useRef<HTMLTextAreaElement>(null);
  const busy = useRef(false);

  useEffect(() => {
    if (initialId === null) return;
    let current = true;
    api
      .getConversation(initialId)
      .then((opened) => {
        if (!current) return;
        setDetail(opened);
        setModel(opened.model);
        setWorkspace(opened.context.workspace ?? "");
        setWebAccess(opened.context.web_access);
        setEntries(opened.messages.map(entryOf));
      })
      .catch((e: unknown) => current && setError(errorText(e)));
    return () => {
      current = false;
    };
  }, [initialId]);

  // A prefilled question is ready to finish typing.
  useEffect(() => {
    const box = questionBox.current;
    if (box === null || initialDraft === "") return;
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
  }, [initialDraft]);

  // Follows the answer as it streams.
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [entries]);

  // The inspector lists every Citation of the chat.
  useEffect(() => {
    onCitations(entries.flatMap((entry) => (entry.role === "assistant" ? entry.citations : [])));
  }, [entries, onCitations]);
  useEffect(() => () => onCitations([]), [onCitations]);

  const loading = initialId !== null && detail === null && error === null;
  // A Conversation that couldn't be loaded isn't continued blind.
  const loadFailed = initialId !== null && detail === null && error !== null;
  // The scope as held: a new chat's, or the saved Conversation's while its Group or Channel still exists.
  const heldScope: Scope | null =
    newScope ?? (detail === null || detail.scope.id === null ? null : { kind: detail.scope.kind, id: detail.scope.id });
  const live = heldScope === null ? null : liveScope(heldScope, groups, channels);
  const listsLoaded = groups !== null && channels !== null;
  const deleted = (detail !== null && detail.scope.id === null) || (heldScope !== null && listsLoaded && live === null);
  // The scope's name as last seen, for when it is deleted while this chat is open.
  const lastName = useRef("");
  if (live !== null) lastName.current = live.name;
  const name = live?.name ?? detail?.scope.name ?? lastName.current;
  const isNew = conversationId === null;

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
          tools: [
            ...a.tools,
            { callId: event.call_id, name: event.name, arguments: event.arguments, state: "running", consulted: [] },
          ],
        }));
      case "tool_result":
        return updateAnswer((a) => ({
          ...a,
          tools: a.tools.map((t) =>
            t.callId === event.call_id
              ? {
                  ...t,
                  state: event.is_error ? "error" : "ok",
                  consulted:
                    !event.is_error && (t.name === "search" || t.name === "expand") ? consultedVideos(event.content) : [],
                }
              : t,
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
    if (busy.current || question === "" || live === null) return;
    busy.current = true;
    setError(null);
    setAnswering(true);
    let shown = false;
    let streamed = false;
    let id = conversationId;
    try {
      if (id === null) {
        const created = await api.createConversation(
          { kind: live.kind, id: live.id },
          model,
          { workspace: workspace.trim() || null, web_access: webAccess },
        );
        id = created.id;
        setWorkspace(created.context.workspace ?? "");
        setWebAccess(created.context.web_access);
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
      if (id !== null) onChanged(id);
    }
  }

  // The stream then ends with an error saying the answer was stopped.
  async function stop() {
    if (conversationId === null) return;
    setStopping(true);
    try {
      await api.stopAnswer(conversationId);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setStopping(false);
    }
  }

  const canAsk = !deleted && !loading && !loadFailed && live !== null && (!isNew || live.unavailable === null);
  const members = live?.members ?? [];
  const syncingNotice = syncingNote(
    members.filter((member) => channelSync(syncs, member.id) !== null).map((member) => member.name),
    members.reduce((ready, member) => ready + member.videos, 0),
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-4 px-6 py-6">
          {loading && <p className="text-sm text-muted-foreground">Loading the chat…</p>}
          {deleted && (
            <Alert>
              <AlertDescription>
                The {(detail?.scope.kind ?? heldScope?.kind) === "channel" ? "channel" : "group"} {name} was removed, so
                this chat can be read but not continued.
              </AlertDescription>
            </Alert>
          )}
          {isNew && entries.length === 0 && live !== null ? (
            <NewChat scope={live} syncs={syncs} onEditGroup={onEditGroup} />
          ) : (
            entries.length > 0 && <Transcript entries={entries} playingKey={playback.playingKey} onPlay={playback.play} />
          )}
          {/* Once the composer is gone its error has nowhere else to show. */}
          {!canAsk && error !== null && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>
      </div>
      {canAsk && (
        <Composer
          name={live.name}
          chip={
            <ScopeChip kind={live.kind} name={live.name} members={live.members.map((m) => m.name)} locked={!isNew} />
          }
          draft={draft}
          onDraft={setDraft}
          questionRef={questionBox}
          model={model}
          onModel={setModel}
          modelLocked={!isNew}
          workspace={workspace}
          onWorkspace={setWorkspace}
          webAccess={webAccess}
          onWebAccess={setWebAccess}
          contextLocked={!isNew}
          answering={answering}
          stopping={stopping}
          canStop={conversationId !== null}
          onAsk={(e) => void ask(e)}
          onStop={() => void stop()}
          notices={notices}
          syncingNotice={syncingNotice}
          error={error}
        />
      )}
    </div>
  );
}
