from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from shorts_bot.config import ConfigurationError, Settings
from shorts_bot.models import ChannelPlatform
from shorts_bot.scheduler import (
    PlatformSchedule,
    due_credits,
    now_in,
    parse_schedule_times,
    platform_schedules,
    schedule_timezone,
)


def test_parse_schedule_times_sorts_and_dedupes() -> None:
    times = parse_schedule_times("18:00, 09:30,18:00")
    assert [t.strftime("%H:%M") for t in times] == ["09:30", "18:00"]


def test_parse_schedule_times_empty() -> None:
    assert parse_schedule_times("") == []


def test_slots_until_counts_passed_slots() -> None:
    schedule = PlatformSchedule(ChannelPlatform.YOUTUBE, parse_schedule_times("09:00,13:00,18:00"))
    assert schedule.slots_until(parse_schedule_times("12:59")[0]) == 1
    assert schedule.slots_until(parse_schedule_times("13:00")[0]) == 2
    assert schedule.slots_until(parse_schedule_times("23:59")[0]) == 3


def test_due_credits_subtracts_uploads_done() -> None:
    schedule = PlatformSchedule(ChannelPlatform.INSTAGRAM, parse_schedule_times("00:00,12:00"))
    local_now = datetime(2026, 9, 25, 18, 0, tzinfo=ZoneInfo("UTC"))
    assert due_credits(schedule, 0, local_now) == 2
    assert due_credits(schedule, 1, local_now) == 1
    assert due_credits(schedule, 5, local_now) == 0


def test_platform_schedules_only_configured() -> None:
    schedules = platform_schedules("09:00", "", "20:00")
    assert set(schedules) == {ChannelPlatform.YOUTUBE, ChannelPlatform.FACEBOOK}


def test_schedule_timezone_named() -> None:
    assert schedule_timezone("Asia/Kolkata").key == "Asia/Kolkata"


def test_now_in_returns_aware_datetime() -> None:
    assert now_in(ZoneInfo("UTC")).tzinfo is not None


def _base_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "YOUTUBE_SCHEDULE_TIMES",
        "INSTAGRAM_SCHEDULE_TIMES",
        "FACEBOOK_SCHEDULE_TIMES",
        "SCHEDULE_TIMEZONE",
        "SUBTITLES_ENABLED",
        "SUBTITLES_WORDS_PER_SCREEN",
        "CHANNELS_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "key")
    monkeypatch.setenv("RIGHTS_ACKNOWLEDGED", "true")
    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("CHANNEL_CONFIG_FILE", str(tmp_path / "missing.toml"))


def test_config_accepts_valid_schedule(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("YOUTUBE_SCHEDULE_TIMES", "09:30,18:00")
    monkeypatch.setenv("SCHEDULE_TIMEZONE", "Asia/Kolkata")
    settings = Settings.from_env(env_file=None)
    assert settings.youtube_schedule_times == "09:30,18:00"
    assert settings.youtube_upload_immediate is False
    assert settings.instagram_upload_immediate is True


def test_config_rejects_bad_schedule_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("YOUTUBE_SCHEDULE_TIMES", "9:30am")
    with pytest.raises(ConfigurationError, match="YOUTUBE_SCHEDULE_TIMES"):
        Settings.from_env(env_file=None)


def test_config_rejects_bad_timezone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SCHEDULE_TIMEZONE", "Not/AZone")
    with pytest.raises(ConfigurationError, match="SCHEDULE_TIMEZONE"):
        Settings.from_env(env_file=None)


def test_config_scheduled_platforms(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("UPLOAD_YOUTUBE", "true")
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC123")
    monkeypatch.setenv("YOUTUBE_SCHEDULE_TIMES", "10:00")
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "123")
    monkeypatch.setenv("FACEBOOK_ACCESS_TOKEN", "token")
    settings = Settings.from_env(env_file=None)
    assert settings.scheduled_platforms == ("YouTube",)


def test_config_subtitle_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    settings = Settings.from_env(env_file=None)
    assert settings.subtitles_enabled is True
    assert settings.subtitles_words_per_screen == 4
    assert settings.subtitles_font_name == "Anton"
    assert settings.channel_scan_max_videos == 5
