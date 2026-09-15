import type { Group } from "@/lib/api";
import { AvatarStack } from "@/components/Avatar";
import { ListRow } from "@/shell/ListRow";

export function GroupList({
  groups,
  selectedId,
  onSelect,
}: {
  groups: Group[];
  selectedId: number | null;
  onSelect: (group: Group) => void;
}) {
  if (groups.length === 0) {
    return <p className="px-2 py-3 text-xs text-muted-foreground">No groups yet</p>;
  }
  return (
    <ul className="space-y-0.5">
      {groups.map((group) => (
        <li key={group.id}>
          <ListRow selected={group.id === selectedId} onClick={() => onSelect(group)}>
            <AvatarStack names={group.channels.map((c) => c.name)} shape="square" size="sm" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{group.name}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {group.channels.length === 0 ? "No channels yet" : group.channels.map((c) => c.name).join(", ")}
              </span>
            </span>
          </ListRow>
        </li>
      ))}
    </ul>
  );
}
