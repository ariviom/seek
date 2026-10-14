import { useEffect, useRef, useState, type ReactNode } from "react";
import { PanelLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

const wide = "(min-width: 1024px)";

// The main pane's header. Below 1024px the list column is gone from the layout, so `list` opens it in a Sheet.
export function MainHeader({
  title,
  right,
  list,
}: {
  title?: ReactNode;
  right?: ReactNode;
  list?: { key: string; title: string; content: ReactNode };
}) {
  const [open, setOpen] = useState(false);
  const listKey = list?.key;
  // What was open when the Sheet opened: after a choice the new view keeps the focus, after a dismissal the button gets it back.
  const openedAt = useRef(listKey);

  // Choosing a row in the Sheet changes what is open, so the Sheet has done its job and gets out of the way.
  useEffect(() => setOpen(false), [listKey]);
  // Above the breakpoint the column is in the layout again, so the Sheet would be a second copy of it.
  useEffect(() => {
    const query = window.matchMedia(wide);
    const onChange = () => {
      if (query.matches) setOpen(false);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
      {list !== undefined && (
        <Sheet
          open={open}
          onOpenChange={(next) => {
            if (next) openedAt.current = listKey;
            setOpen(next);
          }}
        >
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Show list" className="lg:hidden">
              <PanelLeft />
            </Button>
          </SheetTrigger>
          <SheetContent
            side="left"
            className="w-[260px] p-0"
            onCloseAutoFocus={(e) => openedAt.current !== listKey && e.preventDefault()}
          >
            <SheetTitle className="sr-only">{list.title}</SheetTitle>
            {list.content}
          </SheetContent>
        </Sheet>
      )}
      <div className="min-w-0 flex-1 truncate text-sm font-medium">{title}</div>
      {right}
    </header>
  );
}
