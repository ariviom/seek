import type { ComponentProps, ReactNode } from "react";
import { Library, MessageSquare, Monitor, Moon, RefreshCw, Search, Settings, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
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

// Each entry: an icon in a fixed slot, so the icons never move, and a label the expanded rail fades in beside it.
// Takes every Button prop too, so a menu or tooltip trigger wrapping it (asChild) still reaches the button.
function RailButton({
  label,
  name = label,
  current,
  className,
  children,
  ...props
}: ComponentProps<typeof Button> & { label: string; name?: string; current?: boolean; children: ReactNode }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      {...props}
      aria-label={name}
      aria-current={current ? "page" : undefined}
      className={cn(
        "relative md:w-full md:justify-start md:gap-3 md:px-2.5",
        current && "bg-accent text-accent-foreground",
        className,
      )}
    >
      {children}
      <span
        aria-hidden
        className="hidden truncate opacity-0 transition-opacity duration-150 group-hover/rail:opacity-100 group-has-[:focus-visible]/rail:opacity-100 md:inline"
      >
        {label}
      </span>
    </Button>
  );
}

// The icon rail, or a bottom bar below 768px, where a left column would crowd the page. From 768px the rail keeps
// its 48px column in the layout and widens over the page while hovered (after a beat, so passing over it doesn't
// flash it open) or while a key has focused something in it; a click alone doesn't hold it open.
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
  const current = themes.find((t) => t.value === theme);
  const ThemeIcon = current?.Icon ?? Monitor;

  return (
    <nav
      aria-label="Sections"
      className="fixed inset-x-0 bottom-0 z-20 h-14 w-full border-t bg-sidebar md:relative md:inset-auto md:h-auto md:w-12 md:shrink-0 md:border-t-0"
    >
      <div className="group/rail flex h-full w-full flex-row items-center justify-center gap-1 overflow-hidden md:absolute md:inset-y-0 md:left-0 md:z-30 md:w-12 md:flex-col md:items-stretch md:justify-start md:border-r md:bg-sidebar md:px-1.5 md:py-2 md:transition-[width,box-shadow] md:duration-200 md:ease-out md:hover:w-52 md:hover:shadow-lg md:hover:delay-150 md:has-[:focus-visible]:w-52 md:has-[:focus-visible]:shadow-lg">
        {/* Seek's mark: the K of the wordmark, a player's "previous" icon (docs/brand/seek-mark.svg). */}
        <div className="hidden h-9 shrink-0 items-center px-2.5 md:mb-1 md:flex">
          <svg aria-hidden viewBox="0 -1 82 102" className="h-5 w-auto fill-brand">
            <rect x="0" y="0" width="20" height="100" />
            <polygon points="27,50 82,-1 82,101" />
          </svg>
        </div>
        {sections.map(({ view: section, label, Icon }) => (
          <RailButton
            key={section}
            label={label}
            name={section === "syncs" && running ? "Syncs, running" : label}
            current={view === section}
            onClick={() => onView(section)}
          >
            <Icon />
            {section === "syncs" && running && (
              <span aria-hidden className="absolute top-1 right-1 size-1.5 rounded-full bg-amber-400 md:right-auto md:left-6" />
            )}
          </RailButton>
        ))}
        {/* Settings sits with the theme and the health dot: it is what the user owns, not another section of
            the knowledge base. */}
        <div className="flex flex-row items-center gap-1 md:mt-auto md:flex-col md:items-stretch">
          <RailButton label="Settings" current={view === "settings"} onClick={() => onView("settings")}>
            <Settings />
          </RailButton>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <RailButton label={`Theme: ${current?.label ?? "System"}`} name="Theme">
                <ThemeIcon />
              </RailButton>
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
              <RailButton label="Server health" name={`Health: ${dot.text}`} onClick={onShowHealth}>
                <span aria-hidden className="flex size-4 shrink-0 items-center justify-center">
                  <span className={`size-2.5 rounded-full ${dot.tone}`} />
                </span>
              </RailButton>
            </TooltipTrigger>
            <TooltipContent side="right">{dot.text}</TooltipContent>
          </Tooltip>
          {/* The dot's reason, announced without waiting for a hover. */}
          <span role="status" className="sr-only">
            {dot.text}
          </span>
        </div>
      </div>
    </nav>
  );
}
