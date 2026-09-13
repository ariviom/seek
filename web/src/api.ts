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
async function request<T>(path: string, init?: { method: "POST" | "PATCH" | "DELETE"; body?: unknown }): Promise<T> {
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
};
