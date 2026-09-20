import type { FormEvent, ReactNode, Ref } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { EngineName } from "@/lib/api";
import { ChatContext } from "./ChatContext";

const defaultModel = "default";
// Sent as null, which leaves the turn on whatever the default model setting says.
const unpinned = { value: defaultModel, label: "Follow my default model setting" };
// A pin is only ever offered from the engine that would receive it: the API takes model ids, the CLI aliases.
const engineModels: Record<EngineName, { value: string; label: string }[]> = {
  api: [
    { value: "claude-sonnet-5", label: "Sonnet 5 (fast)" },
    { value: "claude-opus-5", label: "Opus 5 (deep)" },
  ],
  cli: [
    { value: "opus", label: "Opus" },
    { value: "sonnet", label: "Sonnet" },
    { value: "haiku", label: "Haiku" },
  ],
};

// A Conversation can be pinned to a model the active engine doesn't offer; show it as stored rather than lose it.
export function modelLabel(model: string | null, engine: EngineName | null): string {
  if (model === null) return unpinned.label;
  const known = engine === null ? [...engineModels.api, ...engineModels.cli] : engineModels[engine];
  return known.find((m) => m.value === model)?.label ?? model;
}

// The question box with who answers, the model, and Ask/Stop. The send flow itself lives with the conversation.
export function Composer({
  name,
  chip,
  draft,
  onDraft,
  questionRef,
  engine,
  model,
  onModel,
  modelLocked,
  workspace,
  onWorkspace,
  webAccess,
  onWebAccess,
  contextLocked,
  answering,
  stopping,
  canStop,
  onAsk,
  onStop,
  notices,
  syncingNotice,
  error,
}: {
  name: string;
  chip: ReactNode;
  draft: string;
  onDraft: (draft: string) => void;
  questionRef: Ref<HTMLTextAreaElement>;
  // The engine that would answer the next turn, which decides the models on offer; null when none can.
  engine: EngineName | null;
  model: string | null;
  onModel: (model: string | null) => void;
  modelLocked: boolean;
  workspace: string;
  onWorkspace: (workspace: string) => void;
  webAccess: boolean;
  onWebAccess: (enabled: boolean) => void;
  contextLocked: boolean;
  answering: boolean;
  stopping: boolean;
  canStop: boolean;
  onAsk: (event: FormEvent) => void;
  onStop: () => void;
  notices: ReactNode;
  // What a Channel still syncing means for the answers, when one is.
  syncingNotice: string | null;
  error: string | null;
}) {
  const offered = engine === null ? [] : engineModels[engine];
  const options =
    model === null || offered.some((m) => m.value === model)
      ? [unpinned, ...offered]
      : [unpinned, ...offered, { value: model, label: modelLabel(model, engine) }];
  return (
    <div className="shrink-0 px-4 pb-3">
      <div className="mx-auto max-w-3xl space-y-2">
        {notices}
        {error !== null && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <form
          aria-label={`Ask ${name}`}
          onSubmit={onAsk}
          className="rounded-xl border bg-card shadow-xs focus-within:border-ring"
        >
          <Textarea
            ref={questionRef}
            rows={2}
            className="max-h-60 min-h-14 resize-none border-0 bg-transparent px-3.5 pt-3 shadow-none focus-visible:ring-0 dark:bg-transparent"
            placeholder={`Ask ${name}`}
            value={draft}
            onChange={(e) => onDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            aria-label={`Question for ${name}`}
          />
          <div className="flex items-center gap-1.5 px-2 pb-2">
            {chip}
            {/* The API engine refuses a project directory or web access, so it offers neither. */}
            {engine !== "api" && (
              <ChatContext
                workspace={workspace}
                onWorkspace={onWorkspace}
                webAccess={webAccess}
                onWebAccess={onWebAccess}
                locked={contextLocked}
              />
            )}
            <span className="flex-1" />
            {modelLocked ? (
              <span className="px-1.5 text-xs text-muted-foreground">{modelLabel(model, engine)}</span>
            ) : (
              <Select
                value={model ?? defaultModel}
                onValueChange={(value) => onModel(value === defaultModel ? null : value)}
              >
                <SelectTrigger size="sm" aria-label="Model" className="border-transparent text-xs text-muted-foreground shadow-none">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {options.map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {answering ? (
              <Button type="button" size="icon-sm" variant="outline" aria-label={stopping ? "Stopping" : "Stop"} disabled={stopping || !canStop} onClick={onStop}>
                <Square className="size-3 fill-current" />
              </Button>
            ) : (
              <Button type="submit" size="icon-sm" aria-label="Ask" disabled={draft.trim() === ""}>
                <ArrowUp />
              </Button>
            )}
          </div>
        </form>
        {syncingNotice !== null && (
          <p className="text-center text-[11px] text-muted-foreground">{syncingNotice}</p>
        )}
        <p className="text-center text-[11px] text-muted-foreground">
          {workspace.trim() !== "" || webAccess
            ? "Channel advice stays cited. Project and web access are read-only."
            : "Answers come only from what was said on these channels, with links to the moments it was said."}
        </p>
      </div>
    </div>
  );
}
