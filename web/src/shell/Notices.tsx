import { Alert, AlertDescription } from "@/components/ui/alert";
import type { ChatEngineStatus, ChatHealth, EngineName, Models, ModelStatus } from "@/lib/api";

type ServerState = { kind: "loading" } | { kind: "ok" } | { kind: "error"; message: string };

export const modelRoles = ["embedding", "reranker"] as const;
export const modelLabels: Record<keyof Models, string> = { embedding: "embedding model", reranker: "reranking model" };

export const engineNames = ["api", "cli"] as const;
export const engineLabels: Record<EngineName, string> = { api: "Anthropic API", cli: "Claude CLI" };

// An engine's standing in a sentence: its own message when it has one, since that says what to add.
export function describeEngine(status: ChatEngineStatus): string {
  return status.state === "ready" ? "ready" : (status.message ?? status.state.replace("_", " "));
}

function megabytes(bytes: number): string {
  return String(Math.floor(bytes / 1_000_000));
}

export function describeModel(status: ModelStatus): string {
  const device = status.device ? ` on ${status.device.toUpperCase()} (${status.precision})` : "";
  const fallback = status.fallback_reason ? `. CPU fallback: ${status.fallback_reason}` : "";
  switch (status.state) {
    case "downloading":
      return status.total_bytes === null
        ? `downloading, ${megabytes(status.downloaded_bytes ?? 0)} MB`
        : `downloading, ${megabytes(status.downloaded_bytes ?? 0)} of ${megabytes(status.total_bytes)} MB`;
    default:
      return `${status.state}${device}${fallback}`;
  }
}

// What stops the whole app working, at the top of the main pane.
export function ServerNotice({ state, liveUpdatesStopped }: { state: ServerState; liveUpdatesStopped: boolean }) {
  if (state.kind === "error") {
    return (
      <Alert variant="destructive" className="mb-4">
        <AlertDescription>Server unavailable: {state.message}</AlertDescription>
      </Alert>
    );
  }
  if (!liveUpdatesStopped) return null;
  return (
    <Alert variant="destructive" className="mb-4">
      <AlertDescription>Live updates stopped. Reload the page, and sign in again if asked.</AlertDescription>
    </Alert>
  );
}

export function ModelNotice({ models }: { models: Models }) {
  const role = modelRoles.find((r) => models[r].state !== "ready");
  if (role === undefined) return null;
  const status = models[role];
  if (status.state === "failed") {
    // The server's message names the model and says what to do.
    return (
      <p role="alert" className="text-sm text-destructive">
        {status.error ?? `The ${modelLabels[role]} failed to load`}
        {role === "reranker" && " Search is available without reranking; result order may be less accurate."}
      </p>
    );
  }
  return (
    <p role="status" className="text-sm text-muted-foreground">
      The {modelLabels[role]} is {describeModel(status)}.{" "}
      {role === "embedding"
        ? "Search and Syncs wait until it’s ready."
        : "Search is available without reranking while it loads."}
    </p>
  );
}

// Only chat needs an engine, so nothing here says the app is broken. With no active engine both engines' messages
// show, since either one satisfied brings chat back.
export function EngineNotice({ chat }: { chat: ChatHealth }) {
  if (chat.active === null) {
    return (
      <div role="alert" className="space-y-1 text-sm text-destructive">
        <p>Chat has no engine yet. Search, the Library and Syncs work without one.</p>
        <ul className="list-disc pl-5">
          {engineNames.map((name) => (
            <li key={name}>
              {engineLabels[name]}: {describeEngine(chat.engines[name])}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  const status = chat.engines[chat.active];
  if (status.state === "ready") return null;
  return (
    <p role="alert" className="text-sm text-destructive">
      {engineLabels[chat.active]}: {describeEngine(status)}
    </p>
  );
}
