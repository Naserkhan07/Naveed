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
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_HANDLE_RE = re.compile(r"^@?[\w.-]{3,40}$")
_RELATIVE_UPLOAD_RE = re.compile(
    r"^(?:(?:streamed|premiered|published)\s+)?(\d+|a|an|one)\s+"
    r"(second|minute|hour|day|week|month|year)s?\s+ago$",
    re.IGNORECASE,
)


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
    published_at: datetime | None = None
    published_at_approximate: bool = False


def _relative_published_at(value: str) -> datetime | None:
    """Conservatively translate YouTube's relative "n units ago" label."""
    now = datetime.now(UTC)
    cleaned = value.strip().casefold()
    if cleaned == "today":
        return now - timedelta(days=1)
    if cleaned == "yesterday":
        return now - timedelta(days=2)
    match = _RELATIVE_UPLOAD_RE.fullmatch(cleaned)
    if match is None:
        return None
    count_text, unit = match.groups()
    count = 1 if count_text in {"a", "an", "one"} else int(count_text)
    # Relative labels are rounded down, so add one full unit to avoid including
    # an item that could actually be older than the configured lookback.
    unit_seconds = {
        "second": 1,
        "minute": 60,
        "hour": 3_600,
        "day": 86_400,
        "week": 604_800,
        "month": 2_592_000,
        "year": 31_536_000,
    }[unit.casefold()]
    return now - timedelta(seconds=(count + 1) * unit_seconds)


def _published_at(entry: dict[str, object]) -> datetime | None:
    """Read a publication timestamp/date or conservatively parsed relative label."""
    # Prefer date-only upload metadata over a relative timestamp, when yt-dlp
    # supplies both, so it is not mistaken for an exact time.
    for key in ("upload_date", "release_date", "publish_date"):
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        cleaned = value.strip()
        if re.fullmatch(r"\d{8}", cleaned):
            try:
                return datetime.strptime(cleaned, "%Y%m%d").replace(tzinfo=UTC)
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            parsed_relative = _relative_published_at(cleaned)
            if parsed_relative is not None:
                return parsed_relative
            continue
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    for key in ("timestamp", "release_timestamp"):
        value = entry.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return datetime.fromtimestamp(float(value), UTC)
            except (OverflowError, OSError, ValueError):
                continue
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromtimestamp(float(value.strip()), UTC)
            except (OverflowError, OSError, ValueError):
                try:
                    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
                except ValueError:
                    continue
                return (
                    parsed.replace(tzinfo=UTC)
                    if parsed.tzinfo is None
                    else parsed.astimezone(UTC)
                )

    for key in ("published_time_text", "publishedTimeText", "published_time"):
        value = entry.get(key)
        if isinstance(value, str):
            parsed = _relative_published_at(value)
            if parsed is not None:
                return parsed
    return None


def _published_at_approximate(entry: dict[str, object]) -> bool:
    """Whether a flat YouTube-tab timestamp came from relative display text."""
    has_timestamp = entry.get("timestamp") is not None
    has_exact_date = any(
        entry.get(key) for key in ("upload_date", "release_date", "publish_date")
    )
    return has_timestamp and not has_exact_date


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
        # Flat YouTube-tab entries otherwise omit relative publication timestamps.
        "extractor_args": {"youtubetab": {"approximate_date": ["true"]}},
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
                published_at=_published_at(entry),
                published_at_approximate=_published_at_approximate(entry),
            )
        )
    return videos


def _is_within_lookback(
    video: ChannelVideo,
    cutoff: datetime,
    latest_allowed: datetime,
) -> bool:
    if video.published_at is None:
        return False
    earliest_allowed = cutoff + timedelta(minutes=5) if video.published_at_approximate else cutoff
    return earliest_allowed <= video.published_at <= latest_allowed


def discover_new_videos(
    channels_file: Path,
    repository: object,
    max_videos: int = 50,
    lookback_days: int = 4,
) -> tuple[list[ChannelVideo], list[str]]:
    """Return unseen uploads published in the recent lookback window.

    Entries without a usable publication date/timestamp are skipped rather than
    risking an old-source repost. Candidates are oldest-first within each
    channel and round-robin across channels, so one prolific creator cannot
    monopolize a scan. ``repository`` must provide
    ``filter_unseen_channel_videos`` from :class:`~shorts_bot.db.JobRepository`.
    """
    specs = read_channels(channels_file)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=lookback_days)
    latest_allowed = now + timedelta(minutes=5)
    channel_candidates: list[list[ChannelVideo]] = []
    errors: list[str] = []

    for spec in specs:
        try:
            videos = latest_channel_videos(spec, max_videos=max_videos)
        except Exception as exc:  # yt-dlp raises many network-specific errors
            message = f"Channel scan failed for {spec.videos_url}: {exc}"
            logger.warning(message)
            errors.append(message)
            continue

        recent = [
            video
            for video in videos
            if _is_within_lookback(video, cutoff, latest_allowed)
        ]
        unseen_ids = repository.filter_unseen_channel_videos(
            spec.key, [video.video_id for video in recent]
        )
        unseen = [video for video in recent if video.video_id in unseen_ids]
        unseen.sort(key=lambda video: video.published_at or cutoff)
        if unseen:
            channel_candidates.append(unseen)

    new_videos: list[ChannelVideo] = []
    for index in range(max((len(candidates) for candidates in channel_candidates), default=0)):
        new_videos.extend(
            candidates[index]
            for candidates in channel_candidates
            if index < len(candidates)
        )
    return new_videos, errors
