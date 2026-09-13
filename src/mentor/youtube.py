from collections.abc import Sequence

from mentor.ports import ChannelInfo, SourceUnavailable, Transcript, VideoDetails, VideoListing

_NOT_BUILT = "YouTube access is not built yet; Mentors can only be added once the yt-dlp adapter lands"


class YouTubeTranscriptSource:
    """TranscriptSource backed by yt-dlp. Every method is unavailable until the adapter is built."""

    def resolve_channel(self, url_or_handle: str) -> ChannelInfo:
        raise SourceUnavailable(_NOT_BUILT)

    def list_videos(self, channel_id: str) -> Sequence[VideoListing]:
        raise SourceUnavailable(_NOT_BUILT)

    def list_playlist(self, playlist_id: str) -> Sequence[str]:
        raise SourceUnavailable(_NOT_BUILT)

    def fetch_video(self, video_id: str) -> tuple[VideoDetails, Transcript]:
        raise SourceUnavailable(_NOT_BUILT)
