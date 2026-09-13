import { useCallback } from "react";
import { api, errorText, type Video } from "./api";
import { useLiveList, type Reaction, type ServerEvent } from "./events";
import { stageLabels } from "./ui";

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

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

  if (error !== null) return <p className="mt-2 text-sm text-red-800">Could not load Videos: {errorText(error)}</p>;
  if (videos === null) return <p className="mt-2 text-sm text-stone-500">Loading Videos…</p>;
  if (videos.length === 0) return <p className="mt-2 text-sm text-stone-500">No Videos yet. Sync this Channel to discover them.</p>;

  return (
    <div className="mt-2 max-h-96 overflow-y-auto rounded-md border border-stone-100">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-stone-50 text-stone-500">
          <tr>
            <th className="px-2 py-1 font-medium">Video</th>
            <th className="px-2 py-1 font-medium">Published</th>
            <th className="px-2 py-1 text-right font-medium">Length</th>
            <th className="px-2 py-1 font-medium">Stage</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100">
          {videos.map((video) => (
            <tr key={video.id} className="align-top">
              <td className="px-2 py-1">
                <a
                  className="hover:underline"
                  href={`https://www.youtube.com/watch?v=${video.youtube_video_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {video.title}
                </a>
              </td>
              <td className="whitespace-nowrap px-2 py-1 text-stone-500">{video.published_on ?? ""}</td>
              <td className="px-2 py-1 text-right tabular-nums text-stone-500">{formatDuration(video.duration_seconds)}</td>
              <td className="px-2 py-1">
                <span className={video.stage === "failed" ? "text-red-700" : video.stage === "excluded" ? "text-stone-400" : ""}>
                  {stageLabels[video.stage]}
                </span>
                {video.reason && (
                  <span className="block text-stone-500">
                    {video.reason}
                    {video.stage === "failed" && video.permanent_failure === false && " (retried on the next Sync)"}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
