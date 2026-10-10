import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ChevronDown, MoreHorizontal, Plus } from "lucide-react";
import {
  api,
  errorText,
  type Channel,
  type ConversationSummary,
  type Group,
  type Scope,
} from "@/lib/api";
import { Avatar, AvatarStack, type AvatarMember } from "@/components/Avatar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { avatarsOf } from "@/lib/channel-avatars";
import { useChanges } from "@/lib/changes";
import { formatWhen, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { scopeKey } from "./scope";

type Folder = {
  key: string;
  // Null for the trailing folder of chats whose Group or Channel was removed.
  scope: Scope | null;
  name: string;
  members: AvatarMember[];
  chats: ConversationSummary[];
};

// Every Conversation, most recently active first, reloaded whenever `version` changes.
export function useConversations(version: number) {
  const [items, setItems] = useState<ConversationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [changes, setChanges] = useState(0);
  const reload = useCallback(async () => setChanges((c) => c + 1), []);

  useEffect(() => {
    let current = true;
    api.listConversations(null).then(
      (listed) => {
        if (!current) return;
        setItems(listed);
        setError(null);
      },
      (e: unknown) => current && setError(`Could not load chats: ${errorText(e)}`),
    );
    return () => {
      current = false;
    };
  }, [version, changes]);

  return { items, error, reload };
}

// One flat list of Groups and Channels, each holding its chats, the folder with the newest chat first and those with
// none last, alphabetically. The list is already newest first, so a folder ranks by where its first chat appears.
function foldersOf(conversations: ConversationSummary[], groups: Group[], channels: Channel[]): Folder[] {
  const avatars = avatarsOf(channels);
  const live: Folder[] = [
    ...groups.map((group) => ({
      key: scopeKey({ kind: "group", id: group.id }),
      scope: { kind: "group" as const, id: group.id },
      name: group.name,
      members: group.channels.map((c) => ({ name: c.name, src: avatars.get(c.id) })),
      chats: [],
    })),
    ...channels.map((channel) => ({
      key: scopeKey({ kind: "channel", id: channel.id }),
      scope: { kind: "channel" as const, id: channel.id },
      name: channel.name,
      members: [{ name: channel.name, src: channel.avatar_url }],
      chats: [],
    })),
  ];
  const byKey = new Map<string, Folder>(live.map((folder) => [folder.key, folder]));
  const removed: Folder = { key: "removed", scope: null, name: "Removed", members: [], chats: [] };
  for (const chat of conversations) {
    const folder = chat.scope.id === null ? undefined : byKey.get(scopeKey({ kind: chat.scope.kind, id: chat.scope.id }));
    (folder ?? removed).chats.push(chat);
  }
  const rank = (folder: Folder) => {
    const first = folder.chats[0];
    return first === undefined ? Number.POSITIVE_INFINITY : conversations.indexOf(first);
  };
  const sorted = live.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  return removed.chats.length > 0 ? [...sorted, removed] : sorted;
}

const collapsedKey = "chat-folders-collapsed";

function useCollapsed() {
  const [collapsed, setCollapsed] = useState<string[]>(() => {
    try {
      const stored: unknown = JSON.parse(sessionStorage.getItem(collapsedKey) ?? "[]");
      return Array.isArray(stored) ? stored.filter((key): key is string => typeof key === "string") : [];
    } catch {
      return [];
    }
  });
  const toggle = (key: string) => {
    const next = collapsed.includes(key) ? collapsed.filter((k) => k !== key) : [...collapsed, key];
    sessionStorage.setItem(collapsedKey, JSON.stringify(next));
    setCollapsed(next);
  };
  return { collapsed, toggle };
}

function FolderAvatar({ folder, ringClassName }: { folder: Folder; ringClassName?: string }) {
  if (folder.scope?.kind === "channel") return <Avatar name={folder.name} src={folder.members[0]?.src} size="xs" />;
  return <AvatarStack members={folder.members} size="xs" ringClassName={ringClassName} />;
}

// The header's "+": a new chat in any live folder.
export function NewChatMenu({
  groups,
  channels,
  onNewChat,
}: {
  groups: Group[] | null;
  channels: Channel[] | null;
  onNewChat: (scope: Scope) => void;
}) {
  const folders = foldersOf([], groups ?? [], channels ?? []);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="New chat" title="New chat">
          <Plus />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel>New chat in</DropdownMenuLabel>
        {groups === null || channels === null ? (
          <DropdownMenuItem disabled>Loading…</DropdownMenuItem>
        ) : (
          folders.length === 0 && <DropdownMenuItem disabled>Add a channel in the Library first</DropdownMenuItem>
        )}
        {folders.map((folder) => (
          <DropdownMenuItem key={folder.key} onSelect={() => folder.scope !== null && onNewChat(folder.scope)}>
            <FolderAvatar folder={folder} ringClassName="ring-popover" />
            <span className="truncate">{folder.name}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Folders({
  conversations,
  error: loadError,
  groups,
  channels,
  selectedId,
  reload,
  onOpen,
  onNewChat,
  onDeleted,
}: {
  conversations: ConversationSummary[] | null;
  error: string | null;
  groups: Group[] | null;
  channels: Channel[] | null;
  selectedId: number | null;
  reload: () => Promise<void>;
  onOpen: (conversationId: number) => void;
  onNewChat: (scope: Scope) => void;
  onDeleted: (conversationId: number) => void;
}) {
  const { collapsed, toggle } = useCollapsed();
  const [error, setError] = useState<string | null>(null);
  const { act, busy } = useChanges(reload, setError);
  const [renaming, setRenaming] = useState<{ id: number; title: string } | null>(null);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);

  if (conversations === null || groups === null || channels === null) {
    return loadError === null ? (
      <p className="px-2 py-3 text-xs text-muted-foreground">Loading…</p>
    ) : (
      <Alert variant="destructive">
        <AlertDescription>{loadError}</AlertDescription>
      </Alert>
    );
  }

  const folders = foldersOf(conversations, groups, channels);

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (renaming === null) return;
    const { id, title } = renaming;
    if (title.trim() === "") return;
    if (await act(() => api.renameConversation(id, title))) setRenaming(null);
  }

  return (
    <div className="space-y-2">
      {(error ?? loadError) !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error ?? loadError}</AlertDescription>
        </Alert>
      )}
      {conversations.length === 0 && (
        <p className="px-2 pt-1 pb-2 text-xs text-muted-foreground">
          {folders.length === 0
            ? "No chats yet. Add a channel in the Library, then start a chat here."
            : "No chats yet. Start one with + on a group or channel."}
        </p>
      )}
      <nav aria-label="Chats by group or channel">
        {folders.map((folder) => {
          const hidden = collapsed.includes(folder.key);
          return (
            <section key={folder.key} className="mb-1">
              <div className="group/folder flex items-center gap-0.5">
                <button
                  type="button"
                  aria-expanded={!hidden}
                  onClick={() => toggle(folder.key)}
                  className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1.5 text-left outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-ring/50"
                >
                  <ChevronDown
                    className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", hidden && "-rotate-90")}
                    aria-hidden
                  />
                  {folder.scope !== null && <FolderAvatar folder={folder} />}
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{folder.name}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">{folder.chats.length}</span>
                </button>
                {folder.scope !== null && (
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    className="text-muted-foreground opacity-0 group-hover/folder:opacity-100 focus-visible:opacity-100"
                    aria-label={`New chat in ${folder.name}`}
                    title={`New chat in ${folder.name}`}
                    onClick={() => folder.scope !== null && onNewChat(folder.scope)}
                  >
                    <Plus />
                  </Button>
                )}
              </div>
              {!hidden && (
                <ul>
                  {folder.chats.map((chat) => (
                    <li key={chat.id} className="group/chat relative">
                      {renaming?.id === chat.id ? (
                        <form onSubmit={rename} className="py-1 pr-1 pl-6">
                          <Input
                            className="h-7"
                            value={renaming.title}
                            maxLength={200}
                            aria-label="Chat title"
                            autoFocus
                            disabled={busy}
                            onChange={(e) => setRenaming({ id: chat.id, title: e.target.value })}
                            onKeyDown={(e) => e.key === "Escape" && setRenaming(null)}
                          />
                        </form>
                      ) : (
                        <>
                          <button
                            type="button"
                            aria-current={chat.id === selectedId ? "true" : undefined}
                            onClick={() => onOpen(chat.id)}
                            className={cn(
                              "flex w-full flex-col rounded-md py-1.5 pr-8 pl-6 text-left outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-ring/50",
                              chat.id === selectedId && "bg-sidebar-accent",
                            )}
                          >
                            <span className="block w-full truncate text-sm">{chat.title}</span>
                            <span className="block w-full truncate text-xs text-muted-foreground">
                              {folder.scope === null && `${chat.scope.kind === "group" ? "Group" : "Channel"} ${chat.scope.name} · `}
                              {formatWhen(chat.last_message_at ?? chat.created_at)} · {plural(chat.message_count, "message")}
                            </span>
                          </button>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon-xs"
                                aria-label={`Actions for ${chat.title}`}
                                className="absolute top-1.5 right-1 text-muted-foreground opacity-0 group-hover/chat:opacity-100 focus-visible:opacity-100 aria-expanded:opacity-100"
                              >
                                <MoreHorizontal />
                              </Button>
                            </DropdownMenuTrigger>
                            {/* Rename's input and Delete's dialog take focus; handing it back to this button would steal it. */}
                            <DropdownMenuContent align="end" onCloseAutoFocus={(e) => e.preventDefault()}>
                              <DropdownMenuItem onSelect={() => setRenaming({ id: chat.id, title: chat.title })}>
                                Rename
                              </DropdownMenuItem>
                              <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(chat)}>
                                Delete
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </>
                      )}
                    </li>
                  ))}
                  {folder.chats.length === 0 && (
                    <li className="py-1 pl-6 text-xs text-muted-foreground">No chats here yet</li>
                  )}
                </ul>
              )}
            </section>
          );
        })}
      </nav>
      <ConfirmDialog
        title="Delete chat"
        actionLabel="Delete chat"
        open={deleting !== null}
        busy={busy}
        onOpenChange={(open) => !open && setDeleting(null)}
        onConfirm={async () => {
          if (deleting === null) return;
          const { id } = deleting;
          if (await act(() => api.deleteConversation(id))) {
            setDeleting(null);
            onDeleted(id);
          }
        }}
      >
        Delete the chat “{deleting?.title}”? This can’t be undone.
      </ConfirmDialog>
    </div>
  );
}
