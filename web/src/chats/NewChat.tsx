import type { Sync } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { plural } from "@/lib/format";
import { channelSync, syncCounts } from "@/lib/sync-status";
import type { LiveScope } from "./scope";

export function NewChat({
  scope,
  syncs,
  onEditGroup,
}: {
  scope: LiveScope;
  syncs: Sync[] | null;
  onEditGroup: (groupId: number) => void;
}) {
  return (
    <div className="pt-8">
      <h1 className="text-lg font-semibold tracking-tight">New chat in {scope.name}</h1>
      <p className="mt-1.5 max-w-prose text-sm text-muted-foreground">
        {scope.kind === "group"
          ? "These channels answer together. The chat stays in this group; to ask a different set, start a chat in another group."
          : "Only this channel’s videos are consulted. The chat stays with this channel."}
      </p>
      {scope.unavailable !== null && (
        <Alert className="mt-4">
          <AlertDescription>{scope.unavailable}</AlertDescription>
        </Alert>
      )}
      <section className="mt-6 rounded-lg border bg-card">
        <div className="flex h-10 items-center justify-between border-b px-4">
          <h2 className="text-sm font-medium">Who answers</h2>
          {scope.kind === "group" && (
            <Button variant="ghost" size="xs" className="text-muted-foreground" onClick={() => onEditGroup(scope.id)}>
              Edit group
            </Button>
          )}
        </div>
        {scope.members.length === 0 ? (
          <p className="px-4 py-3 text-xs text-muted-foreground">No channels yet.</p>
        ) : (
          <ul className="divide-y">
            {scope.members.map((member) => {
              const running = channelSync(syncs, member.id);
              return (
                <li key={member.id} className="flex items-center gap-3 px-4 py-2.5">
                  <Avatar name={member.name} src={member.avatar_url} size="sm" />
                  <span className="min-w-0 flex-1 truncate text-sm">{member.name}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {plural(member.videos, "video")}
                    {running !== null && ` · ${syncCounts(running)}`}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
