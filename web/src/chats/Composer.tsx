import type { FormEvent, ReactNode, Ref } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { EngineName, ModelChoice } from "@/lib/api";
import { conversationModel, engineModels, modelLabel } from "@/lib/models";
import { ChatContext } from "./ChatContext";

// Chosen in place of a model, and sent as null, which leaves the turn on whatever the default setting says.
const followDefault = "default";

// Why the question box is closed: no engine can answer at all, the engine that would answer can't right now, or
// it is the Anthropic API and this chat holds context only the Claude CLI can serve.
export type Blocked = "no_engine" | "engine_unready" | "context";

// The question box with who answers, the model, and Ask/Stop. The send flow itself lives with the conversation.
export function Composer({
  name,
  chip,
  draft,
  onDraft,
  questionRef,
  engine,
  blocked,
  onOpenSettings,
  model,
  onModel,
  modelLocked,
  defaultChoice,
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
  // Why no question can be sent right now, or null when one can. The server refuses each of these too; asking
  // anyway would only spend a round trip to be told the same thing.
  blocked: Blocked | null;
  onOpenSettings: () => void;
  model: string | null;
  onModel: (model: string | null) => void;
  modelLocked: boolean;
  // The default a chat without a pin follows, for saying which model that is; null until it is known.
  defaultChoice: ModelChoice | null;
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
  const options = [
    { value: followDefault, label: conversationModel(null, defaultChoice, engine) },
    ...offered.map((m) => ({ value: m.value, label: modelLabel(m.value, engine) })),
  ];
  // A pin this engine doesn't offer is still this Conversation's pin, so it stays on the list.
  if (model !== null && !offered.some((m) => m.value === model)) {
    options.push({ value: model, label: modelLabel(model, engine) });
  }
  return (
    <div className="shrink-0 px-4 pb-3">
      <div className="mx-auto max-w-3xl space-y-2">
        {notices}
        {error !== null && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {blocked === "context" && (
          <Alert>
            <AlertDescription className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span>
                {contextLocked
                  ? "This chat was started with project or web access, which only the Claude CLI engine provides. Its context is still saved: switch the engine to the Claude CLI to continue here, or start a new chat."
                  : "Project and web access are Claude CLI capabilities, and the Anthropic API would answer this chat. Remove the context, or switch the engine to the Claude CLI."}
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
            disabled={blocked !== null}
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
              <Button type="submit" size="icon-sm" aria-label="Ask" disabled={blocked !== null || draft.trim() === ""}>
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
