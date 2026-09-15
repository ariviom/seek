import type { ReactNode } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";

// The section's list: a fixed header row with its actions, and everything else scrolling under it.
export function ListColumn({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <aside aria-label={title} className="flex h-full w-[260px] shrink-0 flex-col border-r bg-sidebar">
      <div className="flex h-12 shrink-0 items-center justify-between gap-2 px-3">
        <h2 className="truncate text-sm font-medium">{title}</h2>
        {actions}
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="px-3 pb-4">{children}</div>
      </ScrollArea>
    </aside>
  );
}
