export type ModelStatus = {
  name: string;
  state: "waiting" | "downloading" | "loading" | "ready" | "failed";
  downloaded_bytes: number | null;
  total_bytes: number | null;
  error: string | null;
  device: "cuda" | "mps" | "cpu" | null;
  precision: "bfloat16" | "float32" | null;
  fallback_reason: string | null;
};
export type Models = { embedding: ModelStatus; reranker: ModelStatus };

export type EngineName = "api" | "cli";
// `no_key` and `invalid_key` only happen on the api engine, `missing`, `logged_out` and `api_key` only on the cli one.
export type ChatEngineState =
  | "ready"
  | "missing"
  | "logged_out"
  | "api_key"
  | "no_key"
  | "invalid_key"
  | "unknown";
export type ChatEngineStatus = {
  engine: EngineName;
  state: ChatEngineState;
  cli_path: string | null;
  // What to add for a state other than ready, written for the user; shown as it stands.
  message: string | null;
};
// `active` is the engine the next turn would use; null is the one case where chat can't answer at all.
export type ChatHealth = { active: EngineName | null; engines: Record<EngineName, ChatEngineStatus> };

// Preferences a friend owns, kept apart from the operational settings in the config file. A null engine
// leaves the choice to Seek; `model` is the default a Conversation follows unless it pinned one.
export type ModelChoice = "fast" | "deep";
export type Settings = {
  engine: EngineName | null;
  provider: "anthropic";
  model: ModelChoice;
  // Whether search results and an answer's sources show frames of the moment they cite.
  thumbnails: boolean;
};
// The stored key is never returned: only whether one is there, how it fared, and where it is kept.
export type CredentialStatus = {
  present: boolean;
  validity: "unverified" | "valid" | "invalid";
  store: "keychain" | "file";
  // Why the keychain isn't holding the key, or can't be read, when that is so; shown as it stands.
  fallback_reason: string | null;
};

export type Health = {
  status: string;
  models: Models;
  chat: ChatHealth;
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
// How often the server checks a Channel for new videos, in hours.
export type CheckHours = 6 | 24 | 168;
export type Channel = {
  id: number;
  youtube_channel_id: string;
  name: string;
  indexed: boolean;
  filters: ChannelFilters;
  // Null is off; a paused Channel keeps its setting but isn't checked.
  check_every_hours: CheckHours | null;
  indexed_videos: number;
  failed_videos: number;
  excluded_videos: number;
  // When the Channel's last Sync finished successfully.
  last_synced_at: string | null;
  // The Channel's YouTube avatar, once Add channel or a Sync found one.
  avatar_url: string | null;
};
export type ChannelProposal = { youtube_channel_id: string; name: string };
// A Bundle the server built and holds for one download, at `bundleUrl(id)`.
export type BuiltBundle = {
  id: string;
  name: string;
  videos: number;
  segments: number;
  size_bytes: number;
  playlist_filter_left_out: boolean;
};
// What an import did, and the id the Channel or Playlist it arrived as has in this Library.
export type ImportedBundle = {
  kind: "channel" | "playlist";
  id: number;
  name: string;
  youtube_id: string;
  // False when it was in the Library already, where it keeps its name and settings.
  created: boolean;
  // The filters that arrived with a new Channel; null otherwise.
  filters: ChannelFilters | null;
  added: number;
  already_indexed: number;
  // Videos the Bundle did not fill in, counted by the reason, in the server's words.
  left_out: Record<string, number>;
};
// A Channel some of a Playlist's Videos are credited to, in the Library or not.
export type Creator = { id: number; name: string; avatar_url: string | null };
export type Playlist = {
  id: number;
  youtube_playlist_id: string;
  name: string;
  indexed: boolean;
  check_every_hours: CheckHours | null;
  indexed_videos: number;
  failed_videos: number;
  excluded_videos: number;
  last_synced_at: string | null;
  // When the server next checks it: null while Paused, with checks off, or before its first Sync.
  next_check_at: string | null;
  creators: Creator[];
};
// `video_count` is the videos a Sync would ingest: those YouTube lists with a creator.
export type PlaylistProposal = { youtube_playlist_id: string; title: string; video_count: number };
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
// A Video as a Playlist lists it: under the Channel that made it, which may be outside the Library.
export type PlaylistVideo = Video & { channel_id: number; channel_name: string };
// What a Sync ingests: exactly one of a Channel and a Playlist.
type SyncSource = { channel_id: number; playlist_id: null } | { channel_id: null; playlist_id: number };
export type Sync = SyncSource & {
  id: number;
  // The Channel's or the Playlist's name.
  source_name: string;
  status: "queued" | "running" | "done" | "failed";
  error: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  new_videos: number;
  // Videos this Sync has finished with, done or failed, each counted once however often it was processed.
  completed_videos: number;
  // Of those, the ones that failed: completed work, but nothing a question can be answered from.
  failed_videos: number;
  // Videos this Sync still has to get to; with completed_videos, the whole of its work.
  remaining_videos: number;
  // completed_videos when this run of the Sync was claimed, which is also when started_at was set. The work
  // since counted_from took the time since started_at, so the two always measure the same interval.
  counted_from: number;
  stage_counts: Record<Stage, number>;
  // The title of the Video being fetched, on the event a running Sync publishes as it starts fetching it.
  fetching: string | null;
};

export type PreferRecent = "off" | "gentle" | "strong";
// At most one of `group`, `channels`, and `playlist` (for a Group or Playlist, a number is an id and a string a
// name); none searches everything.
export type SearchRequest = {
  query: string;
  group?: number | string;
  channels?: number[];
  playlist?: number | string;
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
  // The Active Playlists that include the Video.
  playlist_ids: number[];
  score: number;
  url: string;
};

// One tile of a storyboard sheet: the moment it shows, and where in that sheet's grid it is cropped from.
export type Frame = { seconds: number; url: string; column: number; row: number };
// A Video's frames of one cited moment, all cropped out of the same `columns` by `rows` grid. A Video with no
// stored geometry simply isn't in the answer, which is how a strip knows to show nothing.
export type VideoFrames = { columns: number; rows: number; video_id: number; seconds: number; frames: Frame[] };
// The frames one strip wants: `count` of them from `seconds` on, at the Video's own storyboard interval.
export type Moment = { video_id: number; seconds: number; count: number };

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

// A null model follows the default model setting rather than pinning one.
// `scope.id` is null once the Group, Channel, or Playlist is deleted, which leaves the Conversation read-only.
export type ScopeKind = "group" | "channel" | "playlist";
export type Scope = { kind: ScopeKind; id: number };
export type ConversationScope = { kind: ScopeKind; id: number | null; name: string };
export type ChatContext = { workspace: string | null; web_access: boolean };
export type Conversation = {
  id: number;
  scope: ConversationScope;
  model: string | null;
  context: ChatContext;
  created_at: string;
};
// What the provider reported, never an estimate; `complete` is false when a turn ended before all of it arrived.
export type TokenUsage = {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  complete: boolean;
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
  // Null on messages saved before engines were selectable: unknown, not zero.
  engine: EngineName | null;
  model: string | null;
  usage: TokenUsage | null;
};
export type ConversationSummary = Conversation & {
  // The title given to the Conversation, or else its first question, shortened.
  title: string;
  message_count: number;
  last_message_at: string | null;
  usage: TokenUsage;
};
export type ConversationDetail = Conversation & { messages: ChatMessage[]; usage: TokenUsage };
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

// Sends a file as it is, as the request's whole body: `request` sends JSON only. No name goes with it. The content
// type is the one the server takes a Bundle as, and one no page on another site can send without asking first.
async function upload<T>(path: string, file: Blob): Promise<T> {
  const response = await fetch(`api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: file,
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(detailMessage(body, response.status));
  return body as T;
}

// Where a built Bundle is downloaded from, once. Relative like every request, so it follows a proxy prefix too.
export function bundleUrl(id: string): string {
  return `api/bundles/${encodeURIComponent(id)}`;
}

export const api = {
  health: () => request<Health>("health"),
  settings: () => request<Settings>("settings"),
  // Only the fields given change; an explicit null engine restores Seek's own choice.
  updateSettings: (patch: Partial<Settings>) => request<Settings>("settings", { method: "PATCH", body: patch }),
  credentialStatus: () => request<CredentialStatus>("credentials/anthropic"),
  // The key goes one way: the server validates and stores it, and never gives it back.
  saveKey: (key: string) => request<CredentialStatus>("credentials/anthropic", { method: "PUT", body: { key } }),
  deleteKey: () => request<CredentialStatus>("credentials/anthropic", { method: "DELETE" }),
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
  setChannelChecks: (id: number, check_every_hours: CheckHours | null) =>
    request<Channel>(`channels/${id}`, { method: "PATCH", body: { check_every_hours } }),
  deleteChannel: (id: number) => request<void>(`channels/${id}`, { method: "DELETE" }),
  buildChannelBundle: (id: number) => request<BuiltBundle>(`channels/${id}/bundles`, { method: "POST" }),
  listPlaylists: () => request<Playlist[]>("playlists"),
  resolvePlaylist: (playlist: string) =>
    request<PlaylistProposal>("playlists/resolve", { method: "POST", body: { playlist } }),
  createPlaylist: (playlist: string, name: string) =>
    request<Playlist>("playlists", { method: "POST", body: { playlist, name } }),
  listGroups: () => request<Group[]>("groups"),
  createGroup: (name: string) => request<Group>("groups", { method: "POST", body: { name } }),
  renameGroup: (id: number, name: string) =>
    request<Group>(`groups/${id}`, { method: "PATCH", body: { name } }),
  deleteGroup: (id: number) => request<void>(`groups/${id}`, { method: "DELETE" }),
  setGroupMembers: (id: number, channelIds: number[]) =>
    request<Group>(`groups/${id}/members`, { method: "PUT", body: { channel_ids: channelIds } }),
  startSync: (channelId: number) => request<Sync>(`channels/${channelId}/syncs`, { method: "POST" }),
  renamePlaylist: (id: number, name: string) =>
    request<Playlist>(`playlists/${id}`, { method: "PATCH", body: { name } }),
  setPlaylistIndexed: (id: number, indexed: boolean) =>
    request<Playlist>(`playlists/${id}`, { method: "PATCH", body: { indexed } }),
  setPlaylistChecks: (id: number, check_every_hours: CheckHours | null) =>
    request<Playlist>(`playlists/${id}`, { method: "PATCH", body: { check_every_hours } }),
  deletePlaylist: (id: number) => request<void>(`playlists/${id}`, { method: "DELETE" }),
  buildPlaylistBundle: (id: number) => request<BuiltBundle>(`playlists/${id}/bundles`, { method: "POST" }),
  startPlaylistSync: (playlistId: number) => request<Sync>(`playlists/${playlistId}/syncs`, { method: "POST" }),
  // Either kind of Bundle; the answer says which arrived.
  importBundle: (file: File) => upload<ImportedBundle>("bundles", file),
  retryFailed: (channelId: number) => request<Sync>(`channels/${channelId}/retry-failed`, { method: "POST" }),
  retryPlaylistFailed: (playlistId: number) =>
    request<Sync>(`playlists/${playlistId}/retry-failed`, { method: "POST" }),
  retryVideo: (videoId: number) => request<Sync>(`videos/${videoId}/retry`, { method: "POST" }),
  // Queues a Sync for every active Channel and every active Playlist.
  syncAll: () => request<Sync[]>("syncs", { method: "POST" }),
  listSyncs: () => request<Sync[]>("syncs"),
  listVideos: (channelId: number) => request<Video[]>(`channels/${channelId}/videos`),
  listPlaylistVideos: (playlistId: number) => request<PlaylistVideo[]>(`playlists/${playlistId}/videos`),
  search: (body: SearchRequest) => request<SearchResult[]>("search", { method: "POST", body }),
  expand: (segmentId: number) => request<Expansion>(`segments/${segmentId}/expand`),
  // Reads geometry already stored; it never makes Seek fetch anything from YouTube.
  frames: (moments: Moment[]) => request<VideoFrames[]>("frames", { method: "POST", body: { moments } }),
  createConversation: (scope: Scope, model: string | null, context: ChatContext) =>
    request<Conversation>(`${scope.kind}s/${scope.id}/conversations`, {
      method: "POST",
      body: { model, ...context },
    }),
  // Every Conversation, or one Group's, Channel's, or Playlist's.
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
