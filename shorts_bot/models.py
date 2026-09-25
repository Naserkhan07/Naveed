from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ChannelPlatform(StrEnum):
    YOUTUBE = "YouTube"
    INSTAGRAM = "Instagram"
    FACEBOOK = "Facebook"


_platform_id_columns: dict[ChannelPlatform, str] = {
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
    """The publication table column recording a completed upload for a platform."""
    return _platform_id_columns[platform]


def platform_uploaded_at_column(platform: ChannelPlatform) -> str:
    """The publication table column holding that platform's UTC upload timestamp."""
    return _platform_uploaded_at_columns[platform]


@dataclass(frozen=True, slots=True)
class Event:
    """One timestamped activity-feed entry shown on the status panel."""

    ts: str
    kind: str
    message: str


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
    """The metadata container the three platform uploaders consume."""

    start_seconds: float
    duration_seconds: float
    title: str
    description: str
    instagram_caption: str = ""
    selection_reason: str = ""


@dataclass(frozen=True, slots=True)
class InstagramUploadResult:
    media_id: str
    permalink: str


@dataclass(frozen=True, slots=True)
class Publication:
    """One finished HotClip export queued for scheduled publishing."""

    id: str
    mp4_path: str
    cover_path: str | None
    title: str
    description: str
    instagram_caption: str
    source_label: str
    queued_at: str
    youtube_video_id: str | None
    youtube_uploaded_at: str | None
    instagram_media_id: str | None
    instagram_url: str | None
    instagram_uploaded_at: str | None
    facebook_video_id: str | None
    facebook_url: str | None
    facebook_uploaded_at: str | None
    error: str | None

    def platform_id(self, platform: ChannelPlatform) -> str | None:
        if platform is ChannelPlatform.YOUTUBE:
            return self.youtube_video_id
        if platform is ChannelPlatform.INSTAGRAM:
            return self.instagram_media_id
        return self.facebook_video_id

    def published_everywhere(self, platforms: list[ChannelPlatform]) -> bool:
        return all(self.platform_id(platform) for platform in platforms)

    def to_plan(self, duration_seconds: float) -> ShortPlan:
        return ShortPlan(
            start_seconds=0.0,
            duration_seconds=duration_seconds,
            title=self.title,
            description=self.description,
            instagram_caption=self.instagram_caption,
        )
