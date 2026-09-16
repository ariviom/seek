import { AlertCircle, FileSearch, Globe2, Loader2, Search } from "lucide-react";
import type { ChatMessage, Citation } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { formatDuration, plural } from "@/lib/format";
import { playableKey } from "@/lib/playback";
import { cn } from "@/lib/utils";
import { Markdown } from "./Markdown";

export type ToolActivity = {
  callId: string;
  name: string;
  arguments: Record<string, unknown>;
  state: "running" | "ok" | "error";
  // "Channel · Video title" for each Video a search or expand returned; only known while the answer streams.
  consulted: string[];
};
export type Entry =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      text: string;
      tools: ToolActivity[];
      // Known once the answer is saved.
      citations: Citation[];
      state: "streaming" | "done" | "failed";
      error: string | null;
    };
export type Answer = Extract<Entry, { role: "assistant" }>;

export function entryOf(message: ChatMessage): Entry {
  if (message.role === "user") return { role: "user", text: message.content };
  const tools = message.tool_calls.map((tool, index) => ({
    callId: String(index),
    name: tool.name,
    arguments: tool.arguments,
    state: tool.is_error ? ("error" as const) : ("ok" as const),
    consulted: [],
  }));
  return { role: "assistant", text: message.content, tools, citations: message.citations, state: "done", error: null };
}

// The Videos a search or expand result names. The result's text holds one pretty-printed JSON block per result,
// joined by newlines, so only a block starts a line with "{".
export function consultedVideos(content: string): string[] {
  const videos: string[] = [];
  for (const block of content.split(/\n(?=\{)/)) {
    let item: unknown;
    try {
      item = JSON.parse(block);
    } catch {
      continue;
    }
    if (typeof item === "object" && item !== null && "channel_name" in item && "video_title" in item) {
      videos.push(`${String(item.channel_name)} · ${String(item.video_title)}`);
    }
  }
  return videos;
}

const toolLabels: Record<string, (args: Record<string, unknown>) => string> = {
  search: (args) => `Searched “${String(args.query ?? "")}”`,
  expand: () => "Read around a search result",
  get_video: (args) => `Looked up Video ${String(args.video_id ?? "")}`,
  list_groups: () => "Listed the Groups",
  list_channels: () => "Listed the Channels",
  Read: (args) => `Read ${String(args.file_path ?? "a project file")}`,
  Glob: () => "Listed project files",
  Grep: (args) => `Searched project for “${String(args.pattern ?? "")}”`,
  WebFetch: (args) => `Opened ${String(args.url ?? "a web page")}`,
  WebSearch: (args) => `Searched the web for “${String(args.query ?? "")}”`,
};

function toolLabel(tool: ToolActivity): string {
  return toolLabels[tool.name]?.(tool.arguments) ?? tool.name;
}

function ToolIcon({ name }: { name: string }) {
  if (name === "Read" || name === "Glob" || name === "Grep") return <FileSearch aria-hidden />;
  if (name === "WebFetch" || name === "WebSearch") return <Globe2 aria-hidden />;
  return <Search aria-hidden />;
}

export function Transcript({
  entries,
  playingKey,
  onPlay,
}: {
  entries: Entry[];
  playingKey: string | null;
  onPlay: (citation: Citation) => void;
}) {
  return (
    <ol className="space-y-7" aria-label="Conversation">
      {entries.map((entry, index) => (
        <li key={index}>
          {entry.role === "user" ? (
            <p className="ml-auto w-fit max-w-[80%] rounded-lg bg-muted px-3.5 py-2 text-sm leading-6 whitespace-pre-wrap">
              {entry.text}
            </p>
          ) : (
            <AnswerView answer={entry} playingKey={playingKey} onPlay={onPlay} />
          )}
        </li>
      ))}
    </ol>
  );
}

function AnswerView({
  answer,
  playingKey,
  onPlay,
}: {
  answer: Answer;
  playingKey: string | null;
  onPlay: (citation: Citation) => void;
}) {
  const consulted = [...new Set(answer.tools.flatMap((tool) => tool.consulted))];
  return (
    <div className="space-y-2.5">
      {answer.tools.length > 0 && (
        <ul className="flex flex-wrap gap-1" aria-label="Tool calls">
          {answer.tools.map((tool) => (
            <li key={tool.callId}>
              <Badge
                variant="outline"
                className={cn("font-normal text-muted-foreground", tool.state === "error" && "text-destructive")}
              >
                {tool.state === "running" ? (
                  <Loader2 className="motion-safe:animate-spin" aria-hidden />
                ) : tool.state === "error" ? (
                  <AlertCircle aria-hidden />
                ) : (
                  <ToolIcon name={tool.name} />
                )}
                {toolLabel(tool)}
                {tool.state === "error" && " (failed)"}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      {answer.state === "streaming" && consulted.length > 0 && (
        <p className="line-clamp-1 text-xs text-muted-foreground" title={consulted.join("; ")}>
          Consulted {plural(consulted.length, "video")}: {consulted.join("; ")}
        </p>
      )}
      {answer.text !== "" && <Markdown text={answer.text} citations={answer.citations} onPlay={onPlay} />}
      {answer.citations.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 pt-0.5" aria-label="Sources">
          {answer.citations.map((citation) => {
            const key = playableKey(citation);
            return (
              <li key={key}>
                <button
                  type="button"
                  aria-current={key === playingKey ? "true" : undefined}
                  title={`${citation.channel_name} · ${citation.video_title} at ${formatDuration(citation.seconds)}`}
                  onClick={() => onPlay(citation)}
                  className={cn(
                    "inline-flex h-7 max-w-full items-center gap-1.5 rounded-md border pr-2 pl-1.5 text-xs outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/50",
                    key === playingKey && "border-foreground/40 bg-accent",
                  )}
                >
                  <Avatar name={citation.channel_name} size="xs" />
                  <span className="max-w-[15rem] truncate">{citation.video_title}</span>
                  <span className="text-muted-foreground tabular-nums">{formatDuration(citation.seconds)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {answer.state === "streaming" && answer.text === "" && answer.tools.length === 0 && (
        <p className="text-sm text-muted-foreground">Thinking…</p>
      )}
      {answer.error !== null && (
        <Alert variant="destructive">
          <AlertDescription>{answer.error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
