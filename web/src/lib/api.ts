export type ModelStatus = {
  name: string;
  state: "waiting" | "downloading" | "loading" | "ready" | "failed";
  downloaded_bytes: number | null;
  total_bytes: number | null;
  error: string | null;
};
export type Models = { embedding: ModelStatus; reranker: ModelStatus };

// Whether the web chat can run: the Claude CLI is present and logged in. `message` says what to do otherwise.
export type ClaudeCli = {
  state: "ready" | "missing" | "logged_out" | "unknown";
  cli_path: string | null;
  message: string | null;
};

export type Health = {
  status: string;
  models: Models;
  claude_cli: ClaudeCli;
  database: {
    path: string;
    journal_mode: string;
    foreign_keys: boolean;
    busy_timeout_ms: number;
    sqlite_vec: string;
    fts5: boolean;
  };
};

// Each filter is off when null; dates are inclusive YYYY-MM-DD.
export type ChannelFilters = {
  published_after: string | null;
  published_before: string | null;
  playlist_id: string | null;
  most_recent: number | null;
};
export type Channel = {
  id: number;
  youtube_channel_id: string;
  name: string;
  indexed: boolean;
  filters: ChannelFilters;
  indexed_videos: number;
  failed_videos: number;
  excluded_videos: number;
  // When the Channel's last Sync finished successfully.
  last_synced_at: string | null;
};
export type ChannelProposal = { youtube_channel_id: string; name: string };
export type Group = { id: number; name: string; channels: { id: number; name: string }[] };

export type Stage = "discovered" | "transcript_fetched" | "segmented" | "embedded" | "done" | "failed" | "excluded";
export type Video = {
  id: number;
  youtube_video_id: string;
  title: string;
  published_on: string | null;
  duration_seconds: number | null;
  chapters: { title: string; start: number; end: number }[];
  stage: Stage;
  reason: string | null;
  failure_stage: Exclude<Stage, "discovered" | "failed" | "excluded"> | null;
  permanent_failure: boolean | null;
  language: string | null;
  transcript_source: "youtube_auto" | "youtube_manual" | null;
};
export type Sync = {
  id: number;
  channel_id: number;
  channel_name: string;
  status: "queued" | "running" | "done" | "failed";
  error: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  new_videos: number;
  stage_counts: Record<Stage, number>;
  // The title of the Video being fetched, on the event a running Sync publishes as it starts fetching it.
  fetching: string | null;
};

export type PreferRecent = "off" | "gentle" | "strong";
// At most one of `group` (a number is an id, a string a name) and `channels`; neither searches every Channel.
export type SearchRequest = {
  query: string;
  group?: number | string;
  channels?: number[];
  limit?: number;
  prefer_recent?: PreferRecent;
};
export type SearchResult = {
  segment_id: number;
  text: string;
  start_seconds: number;
  // Where the Citation points: the cue that best matched the question.
  matched_seconds: number;
  video_id: number;
  youtube_video_id: string;
  video_title: string;
  published_on: string;
  chapter_title: string | null;
  channel_id: number;
  channel_name: string;
  score: number;
  url: string;
};

// The Transcript around a Segment: its own span, and the timed lines from before it to after it.
export type Expansion = {
  segment_id: number;
  start_seconds: number;
  end_seconds: number;
  video_id: number;
  youtube_video_id: string;
  video_title: string;
  published_on: string | null;
  channel_id: number;
  channel_name: string;
  url: string;
  cues: { start_seconds: number; text: string }[];
};

// A null model uses the Claude CLI's default.
// `scope.id` is null once the Group or Channel is deleted, which leaves the Conversation read-only.
export type ScopeKind = "group" | "channel";
export type Scope = { kind: ScopeKind; id: number };
export type ConversationScope = { kind: ScopeKind; id: number | null; name: string };
export type Conversation = {
  id: number;
  scope: ConversationScope;
  model: string | null;
  created_at: string;
};
export type Citation = {
  video_id: number;
  youtube_video_id: string;
  seconds: number;
  video_title: string;
  channel_id: number | null;
  channel_name: string;
  url: string;
  published_on: string | null;
};
export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  tool_calls: { name: string; arguments: Record<string, unknown>; is_error: boolean }[];
  citations: Citation[];
  created_at: string;
};
export type ConversationSummary = Conversation & {
  // The title given to the Conversation, or else its first question, shortened.
  title: string;
  message_count: number;
  last_message_at: string | null;
};
export type ConversationDetail = Conversation & { messages: ChatMessage[] };
// One turn's stream: text and tool activity as it happens, then the saved answer or an error.
export type ChatStreamEvent =
  | { type: "text"; text: string }
  | { type: "tool_call"; call_id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; call_id: string; content: string; is_error: boolean }
  | { type: "done"; message: ChatMessage }
  | { type: "error"; message: string };

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function detailMessage(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const { detail } = body;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: a list of { msg } objects.
    if (Array.isArray(detail)) {
      return detail
        .map((d: unknown) => (typeof d === "object" && d !== null && "msg" in d ? String(d.msg) : String(d)))
        .join("; ");
    }
  }
  return `Request failed (${status})`;
}

// Relative URLs so requests follow any reverse-proxy path prefix.
async function request<T>(
  path: string,
  init?: { method: "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown },
): Promise<T> {
  const response = await fetch(`api/${path}`, {
    method: init?.method ?? "GET",
    headers: init?.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(detailMessage(body, response.status));
  return body as T;
}

export const api = {
  health: () => request<Health>("health"),
  listChannels: () => request<Channel[]>("channels"),
  resolveChannel: (channel: string) =>
    request<ChannelProposal>("channels/resolve", { method: "POST", body: { channel } }),
  createChannel: (channel: string, name: string) =>
    request<Channel>("channels", { method: "POST", body: { channel, name } }),
  renameChannel: (id: number, name: string) => request<Channel>(`channels/${id}`, { method: "PATCH", body: { name } }),
  setChannelIndexed: (id: number, indexed: boolean) =>
    request<Channel>(`channels/${id}`, { method: "PATCH", body: { indexed } }),
  setChannelFilters: (id: number, filters: ChannelFilters) =>
    request<Channel>(`channels/${id}`, { method: "PATCH", body: { filters } }),
  deleteChannel: (id: number) => request<void>(`channels/${id}`, { method: "DELETE" }),
  listGroups: () => request<Group[]>("groups"),
  createGroup: (name: string) => request<Group>("groups", { method: "POST", body: { name } }),
  renameGroup: (id: number, name: string) =>
    request<Group>(`groups/${id}`, { method: "PATCH", body: { name } }),
  deleteGroup: (id: number) => request<void>(`groups/${id}`, { method: "DELETE" }),
  setGroupMembers: (id: number, channelIds: number[]) =>
    request<Group>(`groups/${id}/members`, { method: "PUT", body: { channel_ids: channelIds } }),
  startSync: (channelId: number) => request<Sync>(`channels/${channelId}/syncs`, { method: "POST" }),
  retryFailed: (channelId: number) => request<Sync>(`channels/${channelId}/retry-failed`, { method: "POST" }),
  retryVideo: (videoId: number) => request<Sync>(`videos/${videoId}/retry`, { method: "POST" }),
  // Queues a Sync for every indexed Channel.
  syncAll: () => request<Sync[]>("syncs", { method: "POST" }),
  listSyncs: () => request<Sync[]>("syncs"),
  listVideos: (channelId: number) => request<Video[]>(`channels/${channelId}/videos`),
  search: (body: SearchRequest) => request<SearchResult[]>("search", { method: "POST", body }),
  expand: (segmentId: number) => request<Expansion>(`segments/${segmentId}/expand`),
  createConversation: (scope: Scope, model: string | null) =>
    request<Conversation>(`${scope.kind}s/${scope.id}/conversations`, { method: "POST", body: { model } }),
  // Every Conversation, or one Group's or Channel's.
  listConversations: (scope: Scope | null) =>
    request<ConversationSummary[]>(
      scope === null ? "conversations" : `conversations?${scope.kind}_id=${scope.id}`,
    ),
  getConversation: (id: number) => request<ConversationDetail>(`conversations/${id}`),
  renameConversation: (id: number, title: string) =>
    request<ConversationSummary>(`conversations/${id}`, { method: "PATCH", body: { title } }),
  deleteConversation: (id: number) => request<void>(`conversations/${id}`, { method: "DELETE" }),
  // Stops the answer under way; its stream ends with an error.
  stopAnswer: (id: number) => request<void>(`conversations/${id}/turn`, { method: "DELETE" }),
  sendMessage,
};

// Posts a message and calls onEvent for each event of the answer's stream until it ends. EventSource can't POST, so
// the stream is read directly. Rejects if the turn can't start (e.g. one is already answering).
async function sendMessage(
  conversationId: number,
  message: string,
  onEvent: (event: ChatStreamEvent) => void,
): Promise<void> {
  const response = await fetch(`api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok || response.body === null) {
    const body: unknown = await response.json().catch(() => null);
    throw new Error(detailMessage(body, response.status));
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      if (frame.startsWith("data: ")) onEvent(JSON.parse(frame.slice("data: ".length)) as ChatStreamEvent);
    }
  }
}
