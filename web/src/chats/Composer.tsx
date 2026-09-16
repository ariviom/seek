import type { FormEvent, ReactNode, Ref } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ChatContext } from "./ChatContext";

const defaultModel = "default";
// Claude CLI aliases; "default" keeps the CLI's own default and is sent as null.
const models: { value: string; label: string }[] = [
  { value: defaultModel, label: "Claude CLI default" },
  { value: "opus", label: "Opus" },
  { value: "sonnet", label: "Sonnet" },
  { value: "haiku", label: "Haiku" },
];

export function modelLabel(model: string | null): string {
  return models.find((m) => m.value === (model ?? defaultModel))?.label ?? model ?? "Claude CLI default";
}

// The question box with who answers, the model, and Ask/Stop. The send flow itself lives with the conversation.
export function Composer({
  name,
  chip,
  draft,
  onDraft,
  questionRef,
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
            <ChatContext
              workspace={workspace}
              onWorkspace={onWorkspace}
              webAccess={webAccess}
              onWebAccess={onWebAccess}
              locked={contextLocked}
            />
            <span className="flex-1" />
            {modelLocked ? (
              <span className="px-1.5 text-xs text-muted-foreground">{modelLabel(model)}</span>
            ) : (
              <Select
                value={model ?? defaultModel}
                onValueChange={(value) => onModel(value === defaultModel ? null : value)}
              >
                <SelectTrigger size="sm" aria-label="Model" className="border-transparent text-xs text-muted-foreground shadow-none">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {models.map((m) => (
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
