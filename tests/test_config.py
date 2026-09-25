from __future__ import annotations

from pathlib import Path

import pytest

from shorts_bot.config import Settings
from shorts_bot.errors import ConfigurationError

_ENV_NAMES = [
    "YTDLP_COOKIES_FROM_BROWSER",
    "YTDLP_BROWSER_PROFILE",
    "YTDLP_COOKIE_FILE",
    "CHANNEL_CONFIG_FILE",
    "UPLOAD_YOUTUBE",
    "UPLOAD_INSTAGRAM",
    "UPLOAD_FACEBOOK",
    "FACEBOOK_PAGE_ID",
    "FACEBOOK_ACCESS_TOKEN",
    "FACEBOOK_GRAPH_API_VERSION",
    "FACEBOOK_LIMIT_COOLDOWN_HOURS",
    "INSTAGRAM_ACCESS_TOKEN",
    "YOUTUBE_PRIVACY_STATUS",
    "WORK_DIR",
    "DATABASE_PATH",
    "LINKS_FILE",
    "DOWNLOADED_LINKS_LOG",
    "CHANNELS_FILE",
    "CHANNEL_SCAN_MAX_VIDEOS",
    "CHANNEL_SCAN_INTERVAL_MINUTES",
    "HOTCLIP_WATCH_DIR",
    "HOTCLIP_EXPORT_DIR",
    "HOTCLIP_MIN_CLIP_AGE_SECONDS",
    "SCHEDULE_TIMEZONE",
    "YOUTUBE_SCHEDULE_TIMES",
    "INSTAGRAM_SCHEDULE_TIMES",
    "FACEBOOK_SCHEDULE_TIMES",
    "YOUTUBE_UPLOADS_PER_SLOT",
    "INSTAGRAM_UPLOADS_PER_SLOT",
    "FACEBOOK_UPLOADS_PER_SLOT",
    "DELETE_UPLOADED_CLIPS",
    "RIGHTS_ACKNOWLEDGED",
    "LINKS_POLL_SECONDS",
    "HASHTAGS_FILE",
    "HASHTAGS_ENABLED",
    "HASHTAGS_YOUTUBE_MAX",
    "HASHTAGS_INSTAGRAM_MAX",
    "HASHTAGS_FACEBOOK_MAX",
    "STATUS_PANEL_ENABLED",
    "STATUS_PANEL_HOST",
    "STATUS_PANEL_PORT",
    "STATUS_STALE_AFTER_SECONDS",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _base_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RIGHTS_ACKNOWLEDGED", "true")
    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("CHANNEL_CONFIG_FILE", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "123456")
    monkeypatch.setenv("FACEBOOK_ACCESS_TOKEN", "page-token")
    monkeypatch.setenv("UPLOAD_INSTAGRAM", "true")
    monkeypatch.setenv("INSTAGRAM_USER_ID", "1789")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "token")


def test_reads_valid_local_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    settings = Settings.from_env(env_file=None)
    settings.validate_queue()

    assert settings.upload_youtube is False
    assert settings.upload_instagram is True
    assert settings.upload_facebook is True
    assert settings.facebook_access_token == "page-token"
    assert settings.hotclip_watch_dir == Path("hotclip-watch")
    assert settings.channel_scan_max_videos == 5
    assert settings.schedule_timezone == ""
    assert settings.youtube_uploads_per_slot == 1
    assert settings.scheduled_platforms == ()
    assert settings.delete_uploaded_clips is False


def test_schedule_spec_lookup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("YOUTUBE_SCHEDULE_TIMES", "mon=07:30;fri=21:30")
    monkeypatch.setenv("YOUTUBE_UPLOADS_PER_SLOT", "7")
    settings = Settings.from_env(env_file=None)
    assert settings.schedule_spec("YouTube") == ("mon=07:30;fri=21:30", 7)
    assert settings.scheduled_platforms == ("YouTube",)


def test_rejects_bad_schedule(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("INSTAGRAM_SCHEDULE_TIMES", "9am")
    with pytest.raises(ConfigurationError, match="INSTAGRAM_SCHEDULE_TIMES"):
        Settings.from_env(env_file=None)


def test_rejects_bad_timezone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SCHEDULE_TIMEZONE", "Mars/Olympus")
    with pytest.raises(ConfigurationError, match="SCHEDULE_TIMEZONE"):
        Settings.from_env(env_file=None)


def test_rejects_out_of_range_uploads_per_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("YOUTUBE_UPLOADS_PER_SLOT", "0")
    with pytest.raises(ConfigurationError, match="YOUTUBE_UPLOADS_PER_SLOT"):
        Settings.from_env(env_file=None)


def test_quota_warning_when_above_default_quota(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("UPLOAD_YOUTUBE", "true")
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC123")
    (tmp_path / "token.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setenv(
        "YOUTUBE_SCHEDULE_TIMES",
        "mon=07:30,13:00,20:30;tue=07:30,13:00,20:30;wed=07:30,13:00,20:30;"
        "thu=07:30,13:00,20:30;fri=07:30,13:00,21:30;sat=08:30,13:30,21:30;"
        "sun=08:30,13:30,21:30",
    )
    monkeypatch.setenv("YOUTUBE_UPLOADS_PER_SLOT", "7")
    settings = Settings.from_env(env_file=None)
    warnings = settings.quota_warnings()
    assert warnings
    assert "YouTube" in warnings[0]
    assert "21" in warnings[0]


def test_no_quota_warning_at_low_volume(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("YOUTUBE_SCHEDULE_TIMES", "09:00")
    settings = Settings.from_env(env_file=None)
    assert settings.quota_warnings() == []


def test_requires_rights_acknowledgement(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("CHANNEL_CONFIG_FILE", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("UPLOAD_INSTAGRAM", "true")
    monkeypatch.setenv("INSTAGRAM_USER_ID", "1789")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "token")
    settings = Settings.from_env(env_file=None)
    with pytest.raises(ConfigurationError, match="RIGHTS_ACKNOWLEDGED"):
        settings.validate_queue()
