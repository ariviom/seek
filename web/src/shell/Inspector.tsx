import { useCallback, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

const wide = "(min-width: 1280px)";

// Whether the right column is showing, remembered for the session. On a narrow window it starts hidden, since the
// main pane needs the room.
export function useInspector() {
  const [open, setOpen] = useState(() => {
    const remembered = sessionStorage.getItem("inspector");
    if (remembered === "open" || remembered === "hidden") return remembered === "open";
    return window.matchMedia(wide).matches;
  });

  const remember = useCallback((next: boolean) => {
    sessionStorage.setItem("inspector", next ? "open" : "hidden");
    setOpen(next);
  }, []);

  return {
    open,
    toggle: useCallback(() => remember(!open), [remember, open]),
    hide: useCallback(() => remember(false), [remember]),
  };
}

export function Inspector({
  title,
  count,
  onHide,
  children,
}: {
  title: string;
  count?: number;
  onHide: () => void;
  children: ReactNode;
}) {
  return (
    <aside aria-label={title} className="flex h-full w-[300px] shrink-0 flex-col border-l">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <h2 className="truncate text-sm font-medium">{title}</h2>
        {count !== undefined && <Badge variant="secondary">{count}</Badge>}
        <Button variant="ghost" size="icon" aria-label="Hide panel" className="ml-auto" onClick={onHide}>
          <X />
        </Button>
      </div>
      {/* Radix wraps the content in a `display: table` box that grows with long rows; block keeps `truncate` working. */}
      <ScrollArea className="min-h-0 flex-1 [&_[data-slot=scroll-area-viewport]>div]:block!">
        <div className="p-3">{children}</div>
      </ScrollArea>
    </aside>
  );
}
