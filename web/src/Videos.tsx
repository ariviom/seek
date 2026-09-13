import { useCallback } from "react";
import { api, errorText, type Video } from "./api";
import { useLiveList, type Reaction, type ServerEvent } from "./events";
import { formatDuration, stageFill, stageLabels } from "./ui";

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

  const note = "mt-3 border-t border-rule pt-3 text-sm";
  if (error !== null) return <p className={`${note} text-oxide`}>Could not load Videos: {errorText(error)}</p>;
  if (videos === null) return <p className={`${note} text-pencil`}>Loading Videos…</p>;
  if (videos.length === 0) return <p className={`${note} text-pencil`}>No Videos yet. Sync this Channel to find them.</p>;

  return (
    <div className="mt-3 max-h-[28rem] overflow-y-auto border-t border-rule">
      <table className="w-full text-left text-[13px]">
        <thead className="sticky top-0 bg-panel text-pencil">
          <tr>
            <th className="py-1.5 pr-3 font-medium">Video</th>
            <th className="py-1.5 pr-3 font-medium whitespace-nowrap">Published</th>
            <th className="py-1.5 pr-3 text-right font-medium">Length</th>
            <th className="py-1.5 font-medium">Stage</th>
          </tr>
        </thead>
        <tbody>
          {videos.map((video) => (
            <tr key={video.id} className="border-t border-rule/60 align-top">
              <td className="py-1.5 pr-3">
                <a
                  className="text-ink decoration-machine/50 underline-offset-2 hover:underline"
                  href={`https://www.youtube.com/watch?v=${video.youtube_video_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {video.title}
                </a>
              </td>
              <td className="py-1.5 pr-3 whitespace-nowrap text-pencil tabular-nums">{video.published_on ?? ""}</td>
              <td className="py-1.5 pr-3 text-right whitespace-nowrap text-pencil tabular-nums">
                {formatDuration(video.duration_seconds)}
              </td>
              <td className="min-w-40 py-1.5">
                <span className="flex items-center gap-1.5">
                  <span aria-hidden className={`size-2.5 shrink-0 rounded-[1px] ${stageFill[video.stage]}`} />
                  <span className={video.stage === "failed" ? "text-oxide" : video.stage === "excluded" ? "text-pencil" : ""}>
                    {stageLabels[video.stage]}
                  </span>
                </span>
                {video.reason && (
                  <span className="mt-0.5 block text-pencil">
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
