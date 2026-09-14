import type { ReactNode } from "react";
import { PanelLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

// The main pane's header. Below 1024px the list column is gone from the layout, so `list` opens it in a Sheet.
export function MainHeader({
  title,
  right,
  list,
}: {
  title?: ReactNode;
  right?: ReactNode;
  list?: { title: string; content: ReactNode };
}) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
      {list !== undefined && (
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Show list" className="lg:hidden">
              <PanelLeft />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-[260px] p-0">
            <SheetTitle className="sr-only">{list.title}</SheetTitle>
            {list.content}
          </SheetContent>
        </Sheet>
      )}
      <div className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">{title}</div>
      {right}
    </header>
  );
}
