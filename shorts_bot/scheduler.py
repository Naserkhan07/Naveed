"""Per-platform upload scheduling.

Each platform can have its own comma-separated local times, e.g.
``YOUTUBE_SCHEDULE_TIMES=09:30,18:00``. When a platform has a schedule,
the pipeline renders clips but leaves its uploads pending; the publisher
uploads the next pending clip when a slot is due. Missed/empty slots
become catch-up credits: as soon as a clip is ready, one credit uploads
one clip until the schedule is back on track.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from .models import ChannelPlatform


def parse_schedule_times(raw: str) -> list[time]:
    """Parse ``09:30,18:00`` into sorted ``datetime.time`` values."""
    times: list[time] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        hour_text, minute_text = token.split(":")
        times.append(time(int(hour_text), int(minute_text)))
    return sorted(set(times))


def schedule_timezone(name: str) -> ZoneInfo:
    """Resolve the configured timezone name (falls back to the system local zone)."""
    if name:
        return ZoneInfo(name)
    local = datetime.now().astimezone().tzinfo
    return local if isinstance(local, ZoneInfo) else ZoneInfo("UTC")


class PlatformSchedule:
    """Computes how many uploads a platform is owed on a given day."""

    def __init__(self, platform: ChannelPlatform, times: list[time]) -> None:
        self.platform = platform
        self.times = times

    def slots_until(self, moment: time) -> int:
        """Number of scheduled times at or before the given time of day."""
        return sum(1 for slot in self.times if slot <= moment)


def platform_schedules(
    youtube_times: str,
    instagram_times: str,
    facebook_times: str,
) -> dict[ChannelPlatform, PlatformSchedule]:
    schedules: dict[ChannelPlatform, PlatformSchedule] = {}
    for platform, raw in (
        (ChannelPlatform.YOUTUBE, youtube_times),
        (ChannelPlatform.INSTAGRAM, instagram_times),
        (ChannelPlatform.FACEBOOK, facebook_times),
    ):
        times = parse_schedule_times(raw)
        if times:
            schedules[platform] = PlatformSchedule(platform, times)
    return schedules


def due_credits(
    schedule: PlatformSchedule,
    uploads_done_today: int,
    local_now: datetime,
) -> int:
    """How many uploads the platform is owed right now (slots passed minus uploads).

    ``local_now`` must already be in the schedule's timezone (use :func:`now_in`).
    """
    owed = schedule.slots_until(local_now.time().replace(tzinfo=None))
    return max(0, owed - uploads_done_today)


def now_in(timezone: ZoneInfo) -> datetime:
    return datetime.now(UTC).astimezone(timezone)
