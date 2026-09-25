from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ChannelPlatform(StrEnum):
    YOUTUBE = "YouTube"
    INSTAGRAM = "Instagram"
    FACEBOOK = "Facebook"


_platform_columns: dict[ChannelPlatform, str] = {
    ChannelPlatform.YOUTUBE: "youtube_video_id",
    ChannelPlatform.INSTAGRAM: "instagram_media_id",
    ChannelPlatform.FACEBOOK: "facebook_video_id",
}

_platform_uploaded_at_columns: dict[ChannelPlatform, str] = {
    ChannelPlatform.YOUTUBE: "youtube_uploaded_at",
    ChannelPlatform.INSTAGRAM: "instagram_uploaded_at",
    ChannelPlatform.FACEBOOK: "facebook_uploaded_at",
}


def platform_column(platform: ChannelPlatform) -> str:
    """The JobClip column that records a completed upload for a platform."""
    return _platform_columns[platform]


def platform_uploaded_at_column(platform: ChannelPlatform) -> str:
    """The JobClip column holding the UTC timestamp of that platform's upload."""
    return _platform_uploaded_at_columns[platform]


class JobStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    UPLOADING = "uploading"
    COMPLETE = "complete"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETE, self.FAILED}


@dataclass(frozen=True, slots=True)
class SourceVideo:
    path: Path
    source_url: str
    video_id: str
    title: str
    uploader: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class ShortPlan:
    start_seconds: float
    duration_seconds: float
    title: str
    description: str
    instagram_caption: str = ""
    selection_reason: str = ""


@dataclass(frozen=True, slots=True)
class WordCue:
    """One spoken word with absolute source-video timing in seconds."""

    word: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    """Timestamped transcript text plus word-level timing for subtitles."""

    text: str
    words: tuple[WordCue, ...]


@dataclass(frozen=True, slots=True)
class InstagramUploadResult:
    media_id: str
    permalink: str


@dataclass(frozen=True, slots=True)
class JobClip:
    job_id: str
    clip_index: int
    start_seconds: float
    duration_seconds: float
    title: str
    description: str
    instagram_caption: str
    metadata_ready: bool
    enhancement_complete: bool
    output_path: str | None
    thumbnail_path: str | None
    youtube_video_id: str | None
    instagram_media_id: str | None
    instagram_url: str | None
    facebook_video_id: str | None
    facebook_url: str | None
    error: str | None

    @property
    def youtube_url(self) -> str | None:
        if not self.youtube_video_id:
            return None
        return f"https://youtube.com/shorts/{self.youtube_video_id}"


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    chat_id: int
    user_id: int
    source_url: str
    status: JobStatus
    progress_message: str
    source_title: str | None
    short_title: str | None
    short_description: str | None
    instagram_caption: str | None
    output_path: str | None
    youtube_video_id: str | None
    instagram_media_id: str | None
    instagram_url: str | None
    facebook_video_id: str | None
    facebook_url: str | None
    archive_path: str | None
    error: str | None
    created_at: str
    updated_at: str

    @property
    def youtube_url(self) -> str | None:
        if not self.youtube_video_id:
            return None
        return f"https://youtube.com/shorts/{self.youtube_video_id}"
