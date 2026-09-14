export type ModelStatus = {
  name: string;
  state: "waiting" | "downloading" | "loading" | "ready" | "failed";
  downloaded_bytes: number | null;
  total_bytes: number | null;
  error: string | null;
};
export type Models = { embedding: ModelStatus; reranker: ModelStatus };

export type Health = {
  status: string;
  models: Models;
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
};
export type Mentor = { id: number; name: string; channels: Channel[] };
export type ChannelProposal = { youtube_channel_id: string; name: string };
export type MentorGroup = { id: number; name: string; mentors: { id: number; name: string }[] };

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
  mentor_name: string;
  status: "queued" | "running" | "done" | "failed";
  error: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  new_videos: number;
  stage_counts: Record<Stage, number>;
};

export type PreferRecent = "off" | "gentle" | "strong";
// At most one of `group` (a number is an id, a string a name) and `mentors`; neither searches every Mentor.
export type SearchRequest = {
  query: string;
  group?: number | string;
  mentors?: number[];
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
  channel_name: string;
  mentor_name: string;
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
  channel_name: string;
  mentor_name: string;
  url: string;
  cues: { start_seconds: number; text: string }[];
};

// A null model uses the Claude CLI's default.
export type Conversation = {
  id: number;
  group_id: number | null;
  group_name: string;
  model: string | null;
  created_at: string;
};
export type Citation = {
  video_id: number;
  youtube_video_id: string;
  seconds: number;
  video_title: string;
  mentor_name: string;
  channel_name: string;
  url: string;
};
export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  tool_calls: { name: string; arguments: Record<string, unknown>; is_error: boolean }[];
  citations: Citation[];
  created_at: string;
};
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
  listMentors: () => request<Mentor[]>("mentors"),
  resolveChannel: (channel: string) =>
    request<ChannelProposal>("channels/resolve", { method: "POST", body: { channel } }),
  createMentor: (name: string, channel: string) =>
    request<Mentor>("mentors", { method: "POST", body: { name, channel } }),
  renameMentor: (id: number, name: string) => request<Mentor>(`mentors/${id}`, { method: "PATCH", body: { name } }),
  deleteMentor: (id: number) => request<void>(`mentors/${id}`, { method: "DELETE" }),
  attachChannel: (mentorId: number, channel: string) =>
    request<Channel>(`mentors/${mentorId}/channels`, { method: "POST", body: { channel } }),
  setChannelIndexed: (id: number, indexed: boolean) =>
    request<Channel>(`channels/${id}`, { method: "PATCH", body: { indexed } }),
  setChannelFilters: (id: number, filters: ChannelFilters) =>
    request<Channel>(`channels/${id}`, { method: "PATCH", body: { filters } }),
  detachChannel: (id: number) => request<void>(`channels/${id}`, { method: "DELETE" }),
  listGroups: () => request<MentorGroup[]>("groups"),
  createGroup: (name: string) => request<MentorGroup>("groups", { method: "POST", body: { name } }),
  renameGroup: (id: number, name: string) =>
    request<MentorGroup>(`groups/${id}`, { method: "PATCH", body: { name } }),
  deleteGroup: (id: number) => request<void>(`groups/${id}`, { method: "DELETE" }),
  setGroupMembers: (id: number, mentorIds: number[]) =>
    request<MentorGroup>(`groups/${id}/members`, { method: "PUT", body: { mentor_ids: mentorIds } }),
  startSync: (channelId: number) => request<Sync>(`channels/${channelId}/syncs`, { method: "POST" }),
  retryFailed: (channelId: number) => request<Sync>(`channels/${channelId}/retry-failed`, { method: "POST" }),
  listSyncs: () => request<Sync[]>("syncs"),
  listVideos: (channelId: number) => request<Video[]>(`channels/${channelId}/videos`),
  search: (body: SearchRequest) => request<SearchResult[]>("search", { method: "POST", body }),
  expand: (segmentId: number) => request<Expansion>(`segments/${segmentId}/expand`),
  createConversation: (groupId: number, model: string | null) =>
    request<Conversation>(`groups/${groupId}/conversations`, { method: "POST", body: { model } }),
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
