import { useCallback, useState } from "react";
import { Library, MessageSquare, Moon, RefreshCw, Search, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, type ClaudeCli, type Models, type Sync } from "@/lib/api";
import { useLiveList, type Reaction, type ServerEvent } from "@/lib/events";
import { useTheme, type Theme } from "@/lib/theme";
import type { View } from "@/lib/url-state";

const sections: { view: View; label: string; Icon: typeof MessageSquare }[] = [
  { view: "chats", label: "Chats", Icon: MessageSquare },
  { view: "search", label: "Search", Icon: Search },
  { view: "library", label: "Library", Icon: Library },
  { view: "syncs", label: "Syncs", Icon: RefreshCw },
];

const themes: { value: Theme; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

function reactToSync(event: ServerEvent): Reaction<Sync> {
  if (event.type === "syncs") return "reload";
  if (event.type !== "sync") return null;
  return (syncs) => [event.sync, ...syncs.filter((s) => s.id !== event.sync.id)];
}

// Green when everything can answer; amber while a model is still arriving; red when one failed or the CLI can't run.
function health(models: Models | null, claude: ClaudeCli | null): { tone: string; text: string } {
  if (models === null || claude === null) return { tone: "bg-muted-foreground", text: "Checking the server…" };
  const failed = ([...Object.entries(models)] as [keyof Models, Models[keyof Models]][]).find(
    ([, status]) => status.state === "failed",
  );
  if (failed) return { tone: "bg-red-500", text: failed[1].error ?? `The ${failed[0]} model failed to load` };
  if (claude.state !== "ready") {
    return { tone: "bg-red-500", text: claude.message ?? "The Claude CLI can't answer right now." };
  }
  const waiting = ([...Object.entries(models)] as [keyof Models, Models[keyof Models]][]).find(
    ([, status]) => status.state !== "ready",
  );
  if (waiting) return { tone: "bg-amber-400", text: `The ${waiting[0]} model is ${waiting[1].state}.` };
  return { tone: "bg-emerald-500", text: "Models and the Claude CLI are ready" };
}

// The icon rail, or a bottom bar below 768px, where a left column would crowd the page.
export function Rail({
  view,
  onView,
  models,
  claude,
  onShowHealth,
}: {
  view: View;
  onView: (view: View) => void;
  models: Models | null;
  claude: ClaudeCli | null;
  onShowHealth: () => void;
}) {
  const load = useCallback(() => api.listSyncs(), []);
  const { items: syncs } = useLiveList(load, reactToSync);
  const running = (syncs ?? []).some((sync) => sync.status === "queued" || sync.status === "running");
  const { theme, setTheme } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const dot = health(models, claude);

  return (
    <nav
      aria-label="Sections"
      className="fixed inset-x-0 bottom-0 z-20 flex h-14 w-full flex-row items-center justify-center gap-1 border-t bg-sidebar md:static md:h-auto md:w-12 md:shrink-0 md:flex-col md:justify-start md:gap-1 md:border-t-0 md:border-r md:py-2"
    >
      <span
        aria-hidden
        className="hidden size-7 items-center justify-center rounded-md bg-primary text-xs font-semibold text-primary-foreground md:flex"
      >
        m
      </span>
      {sections.map(({ view: section, label, Icon }) => (
        <Button
          key={section}
          variant="ghost"
          size="icon"
          aria-label={label}
          aria-current={view === section ? "page" : undefined}
          className={`relative md:mt-1 ${view === section ? "bg-accent text-accent-foreground" : ""}`}
          onClick={() => onView(section)}
        >
          <Icon />
          {section === "syncs" && running && (
            <span aria-hidden className="absolute top-1 right-1 size-1.5 rounded-full bg-amber-400" />
          )}
        </Button>
      ))}
      <div className="flex flex-row items-center gap-1 md:mt-auto md:flex-col">
        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Theme">
              {theme === "dark" ? <Moon /> : <Sun />}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" side="right">
            {themes.map(({ value, label }) => (
              <DropdownMenuItem key={value} onSelect={() => setTheme(value)}>
                {label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              role="status"
              aria-label={`Health: ${dot.text}`}
              className="flex size-9 items-center justify-center rounded-md hover:bg-accent"
              onClick={onShowHealth}
            >
              <span aria-hidden className={`size-2.5 rounded-full ${dot.tone}`} />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">{dot.text}</TooltipContent>
        </Tooltip>
      </div>
    </nav>
  );
}
