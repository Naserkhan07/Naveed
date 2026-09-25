"""Automatic latest-video discovery for a list of YouTube channels.

Reads one channel per line from ``channels.txt`` (``@handle``, channel URL,
or channel ID), lists each channel's newest uploads via yt-dlp metadata
(no API key, no download), and remembers every video it has ever queued in
SQLite so each video is processed exactly once.

Only add channels you own or have explicit permission to repurpose; the
same rights rules as manual links apply.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_HANDLE_RE = re.compile(r"^@?[\w.-]{3,40}$")


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    key: str
    videos_url: str


@dataclass(frozen=True, slots=True)
class ChannelVideo:
    channel_key: str
    video_id: str
    url: str
    title: str


def _normalize_channel(entry: str) -> ChannelSpec | None:
    """Turn one channels.txt line into a canonical /videos tab URL."""
    candidate = entry.strip()
    if not candidate or candidate.startswith("#"):
        return None

    if _CHANNEL_ID_RE.fullmatch(candidate):
        url = f"https://www.youtube.com/channel/{candidate}"
    elif candidate.startswith(("http://", "https://")):
        url = candidate
    elif _HANDLE_RE.fullmatch(candidate):
        handle = candidate if candidate.startswith("@") else f"@{candidate}"
        url = f"https://www.youtube.com/{handle}"
    else:
        return None

    url = url.rstrip("/")
    parts = url.split("/")
    if parts and "youtube.com" in parts[2] and len(parts) >= 4:
        for section in ("videos", "shorts", "streams", "featured", "playlists", "community"):
            if parts[-1] == section:
                parts = parts[:-1]
                break
        url = "/".join(parts)
    videos_url = url if url.endswith("/videos") else f"{url}/videos"
    return ChannelSpec(key=videos_url, videos_url=videos_url)


def read_channels(path: Path) -> list[ChannelSpec]:
    if not path.exists():
        return []
    specs: list[ChannelSpec] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        spec = _normalize_channel(line)
        if spec is not None and spec.key not in {other.key for other in specs}:
            specs.append(spec)
    return specs


def latest_channel_videos(spec: ChannelSpec, max_videos: int = 5) -> list[ChannelVideo]:
    """List a channel's newest uploads using flat yt-dlp metadata only."""
    import yt_dlp

    options = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "playlistend": max_videos,
        "ignoreerrors": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(spec.videos_url, download=False)
    entries = (info or {}).get("entries") or []
    videos: list[ChannelVideo] = []
    for entry in entries:
        if not entry:
            continue
        video_id = str(entry.get("id") or "").strip()
        if not video_id:
            continue
        title = str(entry.get("title") or "").strip() or video_id
        videos.append(
            ChannelVideo(
                channel_key=spec.key,
                video_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=title,
            )
        )
    return videos


def discover_new_videos(
    channels_file: Path,
    repository: object,
    max_videos: int = 5,
) -> tuple[list[ChannelVideo], list[str]]:
    """Return never-before-seen videos plus any per-channel error messages.

    ``repository`` must provide ``filter_unseen_channel_videos`` from
    :class:`~shorts_bot.db.JobRepository`.
    """
    specs = read_channels(channels_file)
    new_videos: list[ChannelVideo] = []
    errors: list[str] = []
    for spec in specs:
        try:
            videos = latest_channel_videos(spec, max_videos=max_videos)
        except Exception as exc:  # yt-dlp raises many network-specific errors
            message = f"Channel scan failed for {spec.videos_url}: {exc}"
            logger.warning(message)
            errors.append(message)
            continue
        unseen_ids = repository.filter_unseen_channel_videos(
            spec.key, [video.video_id for video in videos]
        )
        unseen = [video for video in videos if video.video_id in unseen_ids]
        # Oldest first so channels are processed in upload order.
        new_videos.extend(reversed(unseen))
    return new_videos, errors
