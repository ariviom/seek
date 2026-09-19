import { Alert, AlertDescription } from "@/components/ui/alert";
import type { ClaudeCli, Models, ModelStatus } from "@/lib/api";

type ServerState = { kind: "loading" } | { kind: "ok" } | { kind: "error"; message: string };

export const modelRoles = ["embedding", "reranker"] as const;
export const modelLabels: Record<keyof Models, string> = { embedding: "embedding model", reranker: "reranking model" };

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

export function ClaudeNotice({ claude }: { claude: ClaudeCli }) {
  if (claude.state === "ready") return null;
  return (
    <p role="alert" className="text-sm text-destructive">
      {claude.message ?? "The Claude CLI can't answer right now."}
    </p>
  );
}
