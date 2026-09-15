import { useCallback, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
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

const MIN_WIDTH = 260;
const MAX_WIDTH = 720;
const DEFAULT_WIDTH = 300;
const KEY_STEP = 20;

function clampWidth(width: number): number {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width)));
}

// The panel's width, dragged at its left edge and kept across sessions; the player fills it, so wider means a
// bigger video.
function useInspectorWidth() {
  const [width, setWidth] = useState(() => {
    const remembered = Number(localStorage.getItem("inspector-width"));
    return Number.isFinite(remembered) && remembered > 0 ? clampWidth(remembered) : DEFAULT_WIDTH;
  });
  const resize = useCallback((next: number) => {
    const clamped = clampWidth(next);
    localStorage.setItem("inspector-width", String(clamped));
    setWidth(clamped);
  }, []);
  return { width, resize };
}

function ResizeHandle({ width, onResize }: { width: number; onResize: (width: number) => void }) {
  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = width;
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    document.body.style.cursor = "col-resize";
    const move = (e: PointerEvent) => onResize(startWidth + (startX - e.clientX));
    const stop = () => {
      document.body.style.cursor = "";
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize panel"
      aria-valuemin={MIN_WIDTH}
      aria-valuemax={MAX_WIDTH}
      aria-valuenow={width}
      tabIndex={0}
      className="absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize hover:bg-border/60 focus-visible:bg-ring/40 focus-visible:outline-none"
      onPointerDown={startDrag}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") onResize(width + KEY_STEP);
        else if (event.key === "ArrowRight") onResize(width - KEY_STEP);
        else return;
        event.preventDefault();
      }}
    />
  );
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
  const { width, resize } = useInspectorWidth();
  return (
    <aside aria-label={title} style={{ width }} className="relative flex h-full shrink-0 flex-col border-l">
      <ResizeHandle width={width} onResize={resize} />
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
