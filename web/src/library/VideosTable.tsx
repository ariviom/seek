import { useCallback, useState } from "react";
import { api, errorText, type PlaylistVideo, type Video } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { useChannelAvatars } from "@/lib/channel-avatars";
import { useLiveList, type Reaction, type ServerEvent } from "@/lib/events";
import { formatDuration, stageLabels } from "@/lib/format";
import { stageFill } from "@/syncs/StageRule";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type Shown = "all" | "failed" | "excluded";
const shownLabels: Record<Shown, string> = { all: "All", failed: "Failed", excluded: "Excluded" };

// The API's order: newest first, undated last.
function newestFirst(a: Video, b: Video): number {
  if (a.published_on !== b.published_on) {
    if (a.published_on === null) return 1;
    if (b.published_on === null) return -1;
    return a.published_on < b.published_on ? 1 : -1;
  }
  return b.id - a.id;
}

// A Channel's Videos, newest first, or a Playlist's in the playlist's order, each under its creator.
export function VideosTable({ source }: { source: { kind: "channel" | "playlist"; id: number } }) {
  const { kind, id } = source;
  const load = useCallback(
    (): Promise<(Video | PlaylistVideo)[]> => (kind === "channel" ? api.listVideos(id) : api.listPlaylistVideos(id)),
    [kind, id],
  );
  const react = (event: ServerEvent): Reaction<Video | PlaylistVideo> => {
    if (event.type !== "video" && event.type !== "videos") return null;
    if (kind === "playlist") {
      if (!event.playlist_ids.includes(id)) return null;
      if (event.type === "videos") return "reload";
      // A Video event carries neither its creator's name nor its place in the playlist, so the row keeps its own.
      // A Video new to the Playlist isn't listed yet; it comes with the reload that follows the playlist's listing.
      return (videos) => videos.map((video) => (video.id === event.video.id ? { ...video, ...event.video } : video));
    }
    if (event.channel_id !== id) return null;
    if (event.type === "videos") return "reload";
    return (videos) => [event.video, ...videos.filter((v) => v.id !== event.video.id)].sort(newestFirst);
  };
  const { items: videos, error } = useLiveList(load, react);
  const avatarOf = useChannelAvatars();
  const [shown, setShown] = useState<Shown>("all");
  // The Video being retried, and why the last retry failed. The Video and its Sync arrive as events.
  const [retrying, setRetrying] = useState<number | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);

  async function retry(video: Video) {
    setRetryError(null);
    setRetrying(video.id);
    try {
      await api.retryVideo(video.id);
    } catch (e) {
      setRetryError(`Could not retry ${video.title}: ${errorText(e)}`);
    } finally {
      setRetrying(null);
    }
  }

  if (error !== null) return <p className="text-sm text-destructive">Could not load videos: {errorText(error)}</p>;
  if (videos === null) return <p className="text-sm text-muted-foreground">Loading videos…</p>;
  if (videos.length === 0) {
    return <p className="text-sm text-muted-foreground">No videos yet. Sync this {kind} to find them.</p>;
  }

  const listed = shown === "all" ? videos : videos.filter((video) => video.stage === shown);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Select value={shown} onValueChange={(value) => setShown(value as Shown)}>
          <SelectTrigger size="sm" className="w-44" aria-label="Show videos">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(shownLabels) as Shown[]).map((option) => (
              <SelectItem key={option} value={option}>
                {shownLabels[option]}
                {option !== "all" && ` (${videos.filter((video) => video.stage === option).length})`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {retryError !== null && <p className="text-sm text-destructive">{retryError}</p>}
      </div>
      {listed.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">No {shownLabels[shown].toLowerCase()} videos.</p>
      ) : (
        <div className="mt-3 max-h-[28rem] overflow-y-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr>
                <th className="py-1.5 pr-3 font-medium">Video</th>
                {kind === "playlist" && <th className="py-1.5 pr-3 font-medium">Creator</th>}
                <th className="py-1.5 pr-3 font-medium whitespace-nowrap">Published</th>
                <th className="py-1.5 pr-3 text-right font-medium">Length</th>
                <th className="py-1.5 font-medium">Stage</th>
              </tr>
            </thead>
            <tbody>
              {listed.map((video) => (
                <tr key={video.id} className="border-t align-top">
                  <td className="py-1.5 pr-3">
                    <a
                      className="underline-offset-2 hover:underline"
                      href={`https://www.youtube.com/watch?v=${video.youtube_video_id}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {video.title}
                    </a>
                  </td>
                  {"channel_name" in video && (
                    <td className="py-1.5 pr-3">
                      <span className="flex items-center gap-1.5">
                        <Avatar name={video.channel_name} src={avatarOf(video.channel_id)} size="xs" />
                        {video.channel_name}
                      </span>
                    </td>
                  )}
                  <td className="py-1.5 pr-3 whitespace-nowrap text-muted-foreground tabular-nums">
                    {video.published_on ?? ""}
                  </td>
                  <td className="py-1.5 pr-3 text-right whitespace-nowrap text-muted-foreground tabular-nums">
                    {formatDuration(video.duration_seconds)}
                  </td>
                  <td className="min-w-40 py-1.5">
                    <span className="flex items-center gap-1.5">
                      <span aria-hidden className={`size-2 shrink-0 rounded-full ${stageFill[video.stage]}`} />
                      <span
                        className={
                          video.stage === "failed"
                            ? "text-destructive"
                            : video.stage === "excluded"
                              ? "text-muted-foreground"
                              : ""
                        }
                      >
                        {stageLabels[video.stage]}
                      </span>
                    </span>
                    {video.reason !== null && (
                      <span className="mt-0.5 block text-muted-foreground">
                        {video.reason}
                        {video.stage === "failed" && video.permanent_failure === false && " (retried on the next sync)"}
                      </span>
                    )}
                    {/* A Video's own retry needs its Channel in the Library; a Playlist retries its failures together. */}
                    {video.stage === "failed" && kind === "channel" && (
                      <Button
                        variant="ghost"
                        size="xs"
                        className="-ml-2 mt-1"
                        type="button"
                        onClick={() => void retry(video)}
                        disabled={retrying !== null}
                      >
                        {retrying === video.id ? "Retrying…" : "Retry"}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
