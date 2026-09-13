export type Health = {
  status: string;
  database: {
    path: string;
    journal_mode: string;
    foreign_keys: boolean;
    busy_timeout_ms: number;
    sqlite_vec: string;
    fts5: boolean;
  };
};

export type Channel = { id: number; youtube_channel_id: string; name: string; indexed: boolean };
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
  failure_stage: Stage | null;
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
  detachChannel: (id: number) => request<void>(`channels/${id}`, { method: "DELETE" }),
  listGroups: () => request<MentorGroup[]>("groups"),
  createGroup: (name: string) => request<MentorGroup>("groups", { method: "POST", body: { name } }),
  renameGroup: (id: number, name: string) =>
    request<MentorGroup>(`groups/${id}`, { method: "PATCH", body: { name } }),
  deleteGroup: (id: number) => request<void>(`groups/${id}`, { method: "DELETE" }),
  setGroupMembers: (id: number, mentorIds: number[]) =>
    request<MentorGroup>(`groups/${id}/members`, { method: "PUT", body: { mentor_ids: mentorIds } }),
  startSync: (channelId: number) => request<Sync>(`channels/${channelId}/syncs`, { method: "POST" }),
  listSyncs: () => request<Sync[]>("syncs"),
  listVideos: (channelId: number) => request<Video[]>(`channels/${channelId}/videos`),
};
