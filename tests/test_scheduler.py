from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from shorts_bot.models import ChannelPlatform
from shorts_bot.scheduler import (
    PlatformSchedule,
    ScheduleParseError,
    due_credits,
    now_in,
    parse_schedule_spec,
    platform_schedules,
    schedule_timezone,
)


def test_parse_daily_times() -> None:
    per_day = parse_schedule_spec("18:00, 09:30")
    for day in range(7):
        assert [t.strftime("%H:%M") for t in per_day[day]] == ["09:30", "18:00"]


def test_parse_empty_spec() -> None:
    assert parse_schedule_spec("") == {day: [] for day in range(7)}


def test_parse_per_weekday_spec() -> None:
    per_day = parse_schedule_spec("mon=07:30,20:30;fri=07:30,21:30;sun=08:30")
    assert [t.strftime("%H:%M") for t in per_day[0]] == ["07:30", "20:30"]
    assert [t.strftime("%H:%M") for t in per_day[4]] == ["07:30", "21:30"]
    assert [t.strftime("%H:%M") for t in per_day[6]] == ["08:30"]
    assert per_day[1] == []  # Tuesday has no slots


def test_parse_rejects_mixing_forms() -> None:
    with pytest.raises(ScheduleParseError):
        parse_schedule_spec("08:00;fri=10:00")


def test_parse_rejects_bad_time() -> None:
    with pytest.raises(ScheduleParseError):
        parse_schedule_spec("25:00")
    with pytest.raises(ScheduleParseError):
        parse_schedule_spec("funday=08:00")


def test_uploads_owed_multiplies_slots() -> None:
    per_day = parse_schedule_spec("07:30,13:00,20:30")
    schedule = PlatformSchedule(ChannelPlatform.YOUTUBE, per_day, uploads_per_slot=7)
    noon = datetime(2026, 9, 22, 12, 0, tzinfo=ZoneInfo("UTC"))  # a Tuesday
    assert schedule.uploads_owed_until(1, noon.time()) == 7
    night = datetime(2026, 9, 22, 22, 0, tzinfo=ZoneInfo("UTC"))
    assert schedule.uploads_owed_until(1, night.time()) == 21


def test_due_credits_subtracts_todays_uploads() -> None:
    per_day = parse_schedule_spec("tue=08:00,19:30")
    schedule = PlatformSchedule(ChannelPlatform.INSTAGRAM, per_day, uploads_per_slot=10)
    evening = datetime(2026, 9, 22, 21, 0, tzinfo=ZoneInfo("UTC"))
    assert due_credits(schedule, 0, evening) == 20
    assert due_credits(schedule, 15, evening) == 5
    assert due_credits(schedule, 25, evening) == 0
    monday = datetime(2026, 9, 21, 21, 0, tzinfo=ZoneInfo("UTC"))
    assert due_credits(schedule, 0, monday) == 0  # no Monday slots


def test_platform_schedules_from_specs() -> None:
    schedules = platform_schedules(
        ("mon=08:00", 7),
        ("", 1),
        ("sun=10:00,19:00", 10),
    )
    assert set(schedules) == {ChannelPlatform.YOUTUBE, ChannelPlatform.FACEBOOK}
    assert schedules[ChannelPlatform.YOUTUBE].uploads_per_slot == 7


def test_schedule_timezone_named() -> None:
    assert schedule_timezone("Asia/Kolkata").key == "Asia/Kolkata"


def test_now_in_is_aware() -> None:
    assert now_in(ZoneInfo("UTC")).tzinfo is not None
