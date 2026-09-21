import type { FormEvent, ReactNode, Ref } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { EngineName, ModelChoice, TokenUsage } from "@/lib/api";
import { choiceLabel, conversationModel, engineModels, modelLabel } from "@/lib/models";
import { ChatContext } from "./ChatContext";
import { TokenTotals } from "./TokenTotals";

const followDefault = "default";

// The question box with who answers, the model, and Ask/Stop. The send flow itself lives with the conversation.
export function Composer({
  name,
  chip,
  draft,
  onDraft,
  questionRef,
  engine,
  noEngine,
  onOpenSettings,
  model,
  onModel,
  modelLocked,
  defaultChoice,
  usage,
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
  // True once the server has said no engine can answer, as opposed to not having said yet.
  noEngine: boolean;
  onOpenSettings: () => void;
  model: string | null;
  onModel: (model: string | null) => void;
  modelLocked: boolean;
  // The default a chat without a pin follows, for saying which model that is.
  defaultChoice: ModelChoice;
  // This Conversation's reported totals, or null when nothing has been recorded.
  usage: TokenUsage | null;
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
  const savedContext = workspace.trim() !== "" || webAccess;
  const offered = engine === null ? [] : engineModels[engine];
  // Named the way the locked label and the header badge name it, so following the default reads the same everywhere.
  const unpinned = { value: followDefault, label: `Default: ${choiceLabel(defaultChoice, engine)}` };
  const options =
    model === null || offered.some((m) => m.value === model)
      ? [unpinned, ...offered.map((m) => ({ value: m.value, label: modelLabel(m.value, engine) }))]
      : [
          unpinned,
          ...offered.map((m) => ({ value: m.value, label: modelLabel(m.value, engine) })),
          { value: model, label: modelLabel(model, engine) },
        ];
  return (
    <div className="shrink-0 px-4 pb-3">
      <div className="mx-auto max-w-3xl space-y-2">
        {notices}
        {error !== null && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {engine === "api" && savedContext && contextLocked && (
          <Alert>
            <AlertDescription className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span>
                This chat was started with project or web access, which only the Claude CLI engine provides. Its
                context is still saved: switch the engine to the Claude CLI to continue here, or start a new chat.
              </span>
              <Button type="button" size="sm" variant="outline" onClick={onOpenSettings}>
                Open settings
              </Button>
            </AlertDescription>
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
            disabled={noEngine}
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
            {/* The API engine refuses a project directory or web access, so it offers neither — but a chat that
                already has them keeps showing what it holds rather than appearing to have lost it. */}
            {(engine !== "api" || savedContext) && (
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
              <span className="px-1.5 text-xs text-muted-foreground">
                {conversationModel(model, defaultChoice, engine)}
              </span>
            ) : (
              <Select
                value={model ?? followDefault}
                onValueChange={(value) => onModel(value === followDefault ? null : value)}
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
              <Button type="submit" size="icon-sm" aria-label="Ask" disabled={noEngine || draft.trim() === ""}>
                <ArrowUp />
              </Button>
            )}
          </div>
        </form>
        {syncingNotice !== null && (
          <p className="text-center text-[11px] text-muted-foreground">{syncingNotice}</p>
        )}
        <TokenTotals usage={usage} />
        <p className="text-center text-[11px] text-muted-foreground">
          {workspace.trim() !== "" || webAccess
            ? "Channel advice stays cited. Project and web access are read-only."
            : "Answers come only from what was said on these channels, with links to the moments it was said."}
        </p>
      </div>
    </div>
  );
}
