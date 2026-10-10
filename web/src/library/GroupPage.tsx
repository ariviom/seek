import { useState } from "react";
import { api, type Channel, type Group, type Scope } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useChanges } from "@/lib/changes";
import { plural } from "@/lib/format";
import { RenameForm } from "./RenameForm";

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
  const [deleteOpen, setDeleteOpen] = useState(false);

  const memberIds = group.channels.map((c) => c.id);
  const empty = memberIds.length === 0;

  function toggle(channelId: number, member: boolean) {
    const next = member ? [...memberIds, channelId] : memberIds.filter((id) => id !== channelId);
    void act(() => api.setGroupMembers(group.id, next));
  }

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
            {plural(group.channels.length, "channel")} answer together
          </p>
        </div>
        <div className="flex items-center gap-2">
          {empty && <span className="text-xs text-muted-foreground">Add a channel to this group first</span>}
          <Button size="sm" disabled={empty} onClick={() => onNewChat({ kind: "group", id: group.id })}>
            New chat
          </Button>
        </div>
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
                  <Avatar name={channel.name} src={channel.avatar_url} size="sm" />
                  <span className="min-w-0 flex-1 truncate text-sm">{channel.name}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {plural(channel.indexed_videos, "video")}
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
          <RenameForm
            label="Group name"
            name={group.name}
            onRename={(name) => act(() => api.renameGroup(group.id, name))}
          />
          <Button size="sm" variant="destructive" className="ml-auto" onClick={() => setDeleteOpen(true)}>
            Delete group
          </Button>
        </div>
      </fieldset>

      <ConfirmDialog
        title="Delete group"
        actionLabel="Delete group"
        open={deleteOpen}
        busy={busy}
        onOpenChange={setDeleteOpen}
        onConfirm={async () => {
          if (await act(() => api.deleteGroup(group.id))) {
            setDeleteOpen(false);
            onDeleted();
          }
        }}
      >
        Delete the group {group.name}? Its channels are kept, and its chats stay readable.
      </ConfirmDialog>
    </div>
  );
}
