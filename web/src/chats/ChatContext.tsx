import { FolderOpen, Globe2, Paperclip } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";

function folderName(path: string): string {
  const parts = path.replace(/\/+$/, "").split("/");
  return parts.at(-1) || path;
}

export function ChatContext({
  workspace,
  onWorkspace,
  webAccess,
  onWebAccess,
  locked,
}: {
  workspace: string;
  onWorkspace: (workspace: string) => void;
  webAccess: boolean;
  onWebAccess: (enabled: boolean) => void;
  locked: boolean;
}) {
  const hasWorkspace = workspace.trim() !== "";
  const count = Number(hasWorkspace) + Number(webAccess);
  const label = hasWorkspace ? folderName(workspace.trim()) : webAccess ? "Web" : "Add context";
  const summary = count === 2 ? `${label} + web` : label;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="min-w-0 max-w-32 shrink text-muted-foreground sm:max-w-48"
          aria-label={count === 0 ? "Add chat context" : `Chat context: ${summary}`}
          title={hasWorkspace ? workspace : undefined}
        >
          {hasWorkspace ? (
            <FolderOpen data-icon="inline-start" />
          ) : webAccess ? (
            <Globe2 data-icon="inline-start" />
          ) : (
            <Paperclip data-icon="inline-start" />
          )}
          <span className="truncate">{summary}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-80 gap-4 p-3.5">
        <PopoverHeader>
          <PopoverTitle>Chat context</PopoverTitle>
          <PopoverDescription>
            Add material Claude can inspect alongside the channels in this chat.
          </PopoverDescription>
        </PopoverHeader>

        <div className="space-y-1.5">
          <label htmlFor="chat-workspace" className="flex items-center gap-1.5 text-xs font-medium">
            <FolderOpen className="size-3.5 text-muted-foreground" aria-hidden />
            Project directory
          </label>
          <Input
            id="chat-workspace"
            value={workspace}
            onChange={(event) => onWorkspace(event.target.value)}
            disabled={locked}
            placeholder="/home/you/projects/site"
            spellCheck={false}
            autoComplete="off"
          />
          <p className="text-xs leading-5 text-muted-foreground">
            Claude can read and search files inside this directory.
          </p>
        </div>

        <div className="flex items-start justify-between gap-4 border-t pt-3">
          <div className="space-y-0.5">
            <label htmlFor="chat-web-access" className="flex items-center gap-1.5 text-xs font-medium">
              <Globe2 className="size-3.5 text-muted-foreground" aria-hidden />
              Browse the web
            </label>
            <p className="text-xs leading-5 text-muted-foreground">Search and fetch public pages.</p>
          </div>
          <Switch
            id="chat-web-access"
            checked={webAccess}
            onCheckedChange={onWebAccess}
            disabled={locked}
            aria-label="Browse the web"
          />
        </div>

        <p className="border-t pt-3 text-[11px] leading-4 text-muted-foreground">
          {locked ? "Context is fixed after the first message." : "Access is read-only and stays with this chat."}
        </p>
      </PopoverContent>
    </Popover>
  );
}
