import { useState, type FormEvent } from "react";
import { api, type Channel, type Group, type Scope } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useChanges } from "@/lib/changes";

export function GroupPage({
  group,
  channels,
  refresh,
  onNewChat,
  onDeleted,
}: {
  group: Group;
  channels: Channel[];
  refresh: () => Promise<void>;
  onNewChat: (scope: Scope) => void;
  onDeleted: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const { act, busy } = useChanges(refresh, setError);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const memberIds = group.channels.map((c) => c.id);
  const empty = memberIds.length === 0;

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (renaming !== null && (await act(() => api.renameGroup(group.id, renaming)))) setRenaming(null);
  }

  function toggle(channelId: number, member: boolean) {
    const next = member ? [...memberIds, channelId] : memberIds.filter((id) => id !== channelId);
    void act(() => api.setGroupMembers(group.id, next));
  }

  const newChat = (
    <Button size="sm" disabled={empty} onClick={() => onNewChat({ kind: "group", id: group.id })}>
      New chat
    </Button>
  );

  return (
    <div className="space-y-5">
      {error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex items-start gap-3">
        <Avatar name={group.name} shape="square" size="lg" />
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold tracking-tight">{group.name}</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {group.channels.length} {group.channels.length === 1 ? "channel" : "channels"} answer together
          </p>
        </div>
        {empty ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span tabIndex={0}>{newChat}</span>
            </TooltipTrigger>
            <TooltipContent>Add a channel to this group first</TooltipContent>
          </Tooltip>
        ) : (
          newChat
        )}
      </div>

      <fieldset disabled={busy} className="min-w-0 space-y-5">
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium">Channels</h2>
          {channels.length === 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">Add a channel to start</p>
          ) : (
            <ul className="mt-3 space-y-1">
              {channels.map((channel) => (
                <li key={channel.id} className="flex items-center gap-2.5">
                  <Avatar name={channel.name} size="sm" />
                  <span className="min-w-0 flex-1 truncate text-sm">{channel.name}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {channel.indexed_videos} {channel.indexed_videos === 1 ? "video" : "videos"}
                  </span>
                  <Switch
                    aria-label={`${channel.name} in ${group.name}`}
                    checked={memberIds.includes(channel.id)}
                    onCheckedChange={(checked) => toggle(channel.id, checked)}
                  />
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="flex flex-wrap items-center gap-2">
          {renaming === null ? (
            <Button size="sm" variant="ghost" onClick={() => setRenaming(group.name)}>
              Rename
            </Button>
          ) : (
            <form onSubmit={rename} className="flex flex-wrap items-center gap-2">
              <Input
                className="w-56"
                value={renaming}
                onChange={(e) => setRenaming(e.target.value)}
                aria-label="Group name"
              />
              <Button size="sm" type="submit" disabled={renaming.trim() === ""}>
                Save
              </Button>
              <Button size="sm" variant="ghost" type="button" onClick={() => setRenaming(null)}>
                Cancel
              </Button>
            </form>
          )}
          <Button size="sm" variant="destructive" className="ml-auto" onClick={() => setDeleteOpen(true)}>
            Delete group
          </Button>
        </div>
      </fieldset>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete group</DialogTitle>
          </DialogHeader>
          <p className="text-sm">
            Delete the group {group.name}? Its channels are kept, and its chats stay readable.
          </p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={async () => {
                if (await act(() => api.deleteGroup(group.id))) {
                  setDeleteOpen(false);
                  onDeleted();
                }
              }}
            >
              Delete group
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
