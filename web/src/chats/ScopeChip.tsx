import { Lock } from "lucide-react";
import type { ScopeKind } from "@/lib/api";
import { Avatar, AvatarStack, type AvatarMember } from "@/components/Avatar";

// Who answers, shown in the composer. A chat's scope is chosen by where it starts, so the chip only ever displays it;
// once the chat exists it says so.
export function ScopeChip({
  kind,
  name,
  members,
  locked,
}: {
  kind: ScopeKind;
  name: string;
  members: AvatarMember[];
  locked: boolean;
}) {
  return (
    <span
      title={locked ? "Who answers is fixed once a chat starts" : undefined}
      className="inline-flex h-7 max-w-full min-w-0 items-center gap-1.5 rounded-md border pr-2 pl-1.5 text-xs font-medium"
    >
      {kind === "group" ? (
        <AvatarStack members={members} shape="round" size="xs" ringClassName="ring-card" />
      ) : (
        <Avatar name={name} src={members[0]?.src} size="xs" />
      )}
      <span className="truncate">{name}</span>
      {locked && <Lock className="size-3 shrink-0 text-muted-foreground" aria-hidden />}
    </span>
  );
}
