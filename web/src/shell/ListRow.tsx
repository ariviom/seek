import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// A row in a list column: the whole row is the button that selects it.
export function ListRow({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-current={selected ? "true" : undefined}
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-sidebar-accent",
        selected && "bg-sidebar-accent",
      )}
    >
      {children}
    </button>
  );
}
