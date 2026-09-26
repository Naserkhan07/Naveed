"""Per-platform, per-weekday upload scheduling.

Schedule grammar (per platform env var), local times in 24h ``HH:MM``:

* ``09:30,18:00`` — same slots every day
* ``mon=07:30,13:00,20:30;fri=07:30,13:00,21:30`` — per-weekday slots
  (weekdays not listed get no uploads that day; do not mix the two forms)
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from .models import ChannelPlatform

_DAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ScheduleParseError(ValueError):
    pass


def _parse_times(text: str) -> list[time]:
    times: list[time] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if not _TIME_RE.fullmatch(token):
            raise ScheduleParseError(f"invalid time {token!r} (use 24-hour HH:MM)")
        hour, minute = token.split(":")
        times.append(time(int(hour), int(minute)))
    return sorted(set(times))


def parse_schedule_spec(spec: str) -> dict[int, list[time]]:
    """Parse a schedule string into ``{weekday: [sorted slot times]}`` (0=Monday).

    The result always contains all 7 weekdays; empty lists mean no slots.
    """
    per_day: dict[int, list[time]] = {day: [] for day in range(7)}
    if not spec.strip():
        return per_day

    has_day_sections = "=" in spec
    for section in spec.split(";"):
        section = section.strip()
        if not section:
            continue
        if "=" in section:
            days_text, _, times_text = section.partition("=")
            times = _parse_times(times_text)
            for day_name in days_text.split(","):
                day_name = day_name.strip().lower()
                if day_name not in _DAY_ALIASES:
                    raise ScheduleParseError(
                        f"unknown weekday {day_name!r} (use mon, tue, wed, thu, fri, sat, sun)"
                    )
                per_day[_DAY_ALIASES[day_name]] = times
        elif has_day_sections:
            raise ScheduleParseError(
                f"section {section!r} mixes plain times with day= forms; "
                "use either plain daily times or day= sections, not both."
            )
        else:
            times = _parse_times(section)
            for day in range(7):
                per_day[day] = times
    return per_day


def schedule_timezone(name: str) -> ZoneInfo:
    if name:
        return ZoneInfo(name)
    local = datetime.now().astimezone().tzinfo
    return local if isinstance(local, ZoneInfo) else ZoneInfo("UTC")


class PlatformSchedule:
    def __init__(
        self,
        platform: ChannelPlatform,
        per_day: dict[int, list[time]],
        uploads_per_slot: int = 1,
    ) -> None:
        self.platform = platform
        self.per_day = per_day
        self.uploads_per_slot = max(1, uploads_per_slot)

    def slots_today(self, weekday: int) -> list[time]:
        return self.per_day.get(weekday, [])

    def uploads_owed_until(self, weekday: int, moment: time) -> int:
        """Total uploads owed today (by this time) across all of today's slots."""
        passed = sum(1 for slot in self.slots_today(weekday) if slot <= moment)
        return passed * self.uploads_per_slot


def platform_schedules(
    youtube_spec: tuple[str, int],
    instagram_spec: tuple[str, int],
    facebook_spec: tuple[str, int],
) -> dict[ChannelPlatform, PlatformSchedule]:
    schedules: dict[ChannelPlatform, PlatformSchedule] = {}
    for platform, (raw, per_slot) in (
        (ChannelPlatform.YOUTUBE, youtube_spec),
        (ChannelPlatform.INSTAGRAM, instagram_spec),
        (ChannelPlatform.FACEBOOK, facebook_spec),
    ):
        per_day = parse_schedule_spec(raw)
        if any(per_day.values()):
            schedules[platform] = PlatformSchedule(platform, per_day, per_slot)
    return schedules


def due_credits(
    schedule: PlatformSchedule,
    uploads_done_today: int,
    local_now: datetime,
) -> int:
    """How many uploads the platform is owed right now."""
    owed = schedule.uploads_owed_until(
        local_now.weekday(),
        local_now.time().replace(tzinfo=None),
    )
    return max(0, owed - uploads_done_today)


def now_in(timezone: ZoneInfo) -> datetime:
    return datetime.now(UTC).astimezone(timezone)
