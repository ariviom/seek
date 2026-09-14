import { useCallback, useState } from "react";
import { api, errorText, type Video } from "@/lib/api";
import { useLiveList, type Reaction, type ServerEvent } from "@/lib/events";
import { inputClass, quietButtonClass, stageFill } from "./ui";
import { formatDuration, stageLabels } from "@/lib/format";

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

export function ChannelVideos({ channelId }: { channelId: number }) {
  const load = useCallback(() => api.listVideos(channelId), [channelId]);
  const react = (event: ServerEvent): Reaction<Video> => {
    if (event.type === "videos" && event.channel_id === channelId) return "reload";
    if (event.type !== "video" || event.channel_id !== channelId) return null;
    return (videos) => [event.video, ...videos.filter((v) => v.id !== event.video.id)].sort(newestFirst);
  };
  const { items: videos, error } = useLiveList(load, react);
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

  const note = "mt-3 border-t border-border pt-3 text-sm";
  if (error !== null) return <p className={`${note} text-destructive`}>Could not load Videos: {errorText(error)}</p>;
  if (videos === null) return <p className={`${note} text-muted-foreground`}>Loading Videos…</p>;
  if (videos.length === 0) return <p className={`${note} text-muted-foreground`}>No Videos yet. Sync this Channel to find them.</p>;

  const listed = shown === "all" ? videos : videos.filter((video) => video.stage === shown);

  return (
    <div className="mt-3 border-t border-border pt-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          Show
          <select
            className={`${inputClass} py-1 text-sm`}
            value={shown}
            onChange={(e) => setShown(e.target.value as Shown)}
          >
            {(Object.keys(shownLabels) as Shown[]).map((option) => (
              <option key={option} value={option}>
                {shownLabels[option]}
                {option !== "all" && ` (${videos.filter((video) => video.stage === option).length})`}
              </option>
            ))}
          </select>
        </label>
        {retryError && <p className="text-sm text-destructive">{retryError}</p>}
      </div>
      {listed.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">No {shownLabels[shown].toLowerCase()} Videos.</p>
      ) : (
        <div className="mt-2 max-h-[28rem] overflow-y-auto">
          <table className="w-full text-left text-[13px]">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr>
                <th className="py-1.5 pr-3 font-medium">Video</th>
                <th className="py-1.5 pr-3 font-medium whitespace-nowrap">Published</th>
                <th className="py-1.5 pr-3 text-right font-medium">Length</th>
                <th className="py-1.5 font-medium">Stage</th>
              </tr>
            </thead>
            <tbody>
              {listed.map((video) => (
                <tr key={video.id} className="border-t border-border align-top">
                  <td className="py-1.5 pr-3">
                    <a
                      className="text-foreground decoration-primary/50 underline-offset-2 hover:underline"
                      href={`https://www.youtube.com/watch?v=${video.youtube_video_id}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {video.title}
                    </a>
                  </td>
                  <td className="py-1.5 pr-3 whitespace-nowrap text-muted-foreground tabular-nums">{video.published_on ?? ""}</td>
                  <td className="py-1.5 pr-3 text-right whitespace-nowrap text-muted-foreground tabular-nums">
                    {formatDuration(video.duration_seconds)}
                  </td>
                  <td className="min-w-40 py-1.5">
                    <span className="flex items-center gap-1.5">
                      <span aria-hidden className={`size-2.5 shrink-0 rounded-[1px] ${stageFill[video.stage]}`} />
                      <span className={video.stage === "failed" ? "text-destructive" : video.stage === "excluded" ? "text-muted-foreground" : ""}>
                        {stageLabels[video.stage]}
                      </span>
                    </span>
                    {video.reason && (
                      <span className="mt-0.5 block text-muted-foreground">
                        {video.reason}
                        {video.stage === "failed" && video.permanent_failure === false && " (retried on the next Sync)"}
                      </span>
                    )}
                    {video.stage === "failed" && (
                      <button
                        className={`${quietButtonClass} -ml-2 text-[13px]`}
                        type="button"
                        onClick={() => void retry(video)}
                        disabled={retrying !== null}
                      >
                        {retrying === video.id ? "Retrying…" : "Retry"}
                      </button>
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
