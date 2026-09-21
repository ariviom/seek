import { Library, MessageSquare, Monitor, Moon, RefreshCw, Search, Settings, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ChatHealth, Models, Sync } from "@/lib/api";
import { useTheme, type Theme } from "@/lib/theme";
import type { View } from "@/lib/url-state";
import { describeEngine, describeModel, engineLabels, engineNames, modelLabels, modelRoles } from "./Notices";

const sections: { view: View; label: string; Icon: typeof MessageSquare }[] = [
  { view: "chats", label: "Chats", Icon: MessageSquare },
  { view: "search", label: "Search", Icon: Search },
  { view: "library", label: "Library", Icon: Library },
  { view: "syncs", label: "Syncs", Icon: RefreshCw },
];

const themes: { value: Theme; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
];

// Both engines, marking the one a turn would use, so the dot says which requirement is outstanding.
function engineText(chat: ChatHealth): string {
  return engineNames
    .map((name) => `${engineLabels[name]}${name === chat.active ? " (active)" : ""}: ${describeEngine(chat.engines[name])}`)
    .join(". ");
}

// Green when everything can answer; amber while a model is still arriving; red when the server, a model, or the
// active engine can't. The wording is the one the notices use, so the dot and the notice never disagree.
function health(
  models: Models | null,
  chat: ChatHealth | null,
  serverError: string | null,
): { tone: string; text: string } {
  if (serverError !== null) return { tone: "bg-red-500", text: `Server unavailable: ${serverError}` };
  if (models === null || chat === null) return { tone: "bg-muted-foreground", text: "Checking the server…" };
  const failed = modelRoles.find((role) => models[role].state === "failed");
  if (failed !== undefined) {
    return { tone: "bg-red-500", text: models[failed].error ?? `The ${modelLabels[failed]} failed to load` };
  }
  if (chat.active === null) {
    return { tone: "bg-red-500", text: `Chat has no engine yet. ${engineText(chat)}` };
  }
  if (chat.engines[chat.active].state !== "ready") {
    return { tone: "bg-red-500", text: `Chat can't answer. ${engineText(chat)}` };
  }
  const waiting = modelRoles.find((role) => models[role].state !== "ready");
  if (waiting !== undefined) {
    return { tone: "bg-amber-400", text: `The ${modelLabels[waiting]} is ${describeModel(models[waiting])}` };
  }
  return { tone: "bg-emerald-500", text: `Models are ready. ${engineText(chat)}` };
}

// The icon rail, or a bottom bar below 768px, where a left column would crowd the page.
export function Rail({
  view,
  onView,
  syncs,
  models,
  chat,
  serverError,
  onShowHealth,
}: {
  view: View;
  onView: (view: View) => void;
  syncs: Sync[] | null;
  models: Models | null;
  chat: ChatHealth | null;
  serverError: string | null;
  onShowHealth: () => void;
}) {
  const running = (syncs ?? []).some((sync) => sync.status === "queued" || sync.status === "running");
  const { theme, setTheme } = useTheme();
  const dot = health(models, chat, serverError);
  const ThemeIcon = themes.find((t) => t.value === theme)?.Icon ?? Monitor;

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
          aria-label={section === "syncs" && running ? "Syncs, running" : label}
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
      {/* Settings sits with the theme and the health dot: it is what the user owns, not another section of
          the knowledge base. */}
      <div className="flex flex-row items-center gap-1 md:mt-auto md:flex-col">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Settings"
          aria-current={view === "settings" ? "page" : undefined}
          className={view === "settings" ? "bg-accent text-accent-foreground" : ""}
          onClick={() => onView("settings")}
        >
          <Settings />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Theme">
              <ThemeIcon />
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
            <Button variant="ghost" size="icon" aria-label={`Health: ${dot.text}`} onClick={onShowHealth}>
              <span aria-hidden className={`size-2.5 rounded-full ${dot.tone}`} />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">{dot.text}</TooltipContent>
        </Tooltip>
        {/* The dot's reason, announced without waiting for a hover. */}
        <span role="status" className="sr-only">
          {dot.text}
        </span>
      </div>
    </nav>
  );
}
