from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .errors import ConfigurationError

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}
_SUPPORTED_COOKIE_BROWSERS = {
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ConfigurationError(f"{name} must be true or false, not {value!r}.")


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number.") from exc


def _read_channel_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"Could not read channel configuration {path}: {exc}") from exc


def _nested_string(config: dict[str, Any], section: str, key: str) -> str:
    section_value = config.get(section, {})
    if not isinstance(section_value, dict):
        return ""
    return str(section_value.get(key, "")).strip()


@dataclass(frozen=True, slots=True)
class Settings:
    ytdlp_cookies_from_browser: str
    ytdlp_browser_profile: str
    ytdlp_cookie_file: Path | None
    channel_config_file: Path
    youtube_channel_id: str
    youtube_client_secrets_file: Path
    youtube_token_file: Path
    youtube_privacy_status: str
    upload_youtube: bool
    instagram_user_id: str
    instagram_access_token: str
    instagram_graph_api_version: str
    upload_instagram: bool
    facebook_page_id: str
    facebook_access_token: str
    facebook_graph_api_version: str
    upload_facebook: bool
    facebook_limit_cooldown_hours: float
    youtube_description_target_chars: int
    instagram_caption_target_chars: int
    hotclip_watch_dir: Path
    hotclip_export_dir: Path
    hotclip_min_clip_age_seconds: int
    channels_file: Path
    channel_scan_max_videos: int
    channel_scan_interval_minutes: int
    schedule_timezone: str
    youtube_schedule_times: str
    instagram_schedule_times: str
    facebook_schedule_times: str
    youtube_uploads_per_slot: int
    instagram_uploads_per_slot: int
    facebook_uploads_per_slot: int
    work_dir: Path
    database_path: Path
    delete_uploaded_clips: bool
    rights_acknowledged: bool
    links_file: Path
    downloaded_links_log: Path
    links_poll_seconds: int
    hashtags_file: Path
    hashtags_enabled: bool
    hashtags_youtube_max: int
    hashtags_instagram_max: int
    hashtags_facebook_max: int
    status_panel_enabled: bool
    status_panel_host: str
    status_panel_port: int
    status_stale_after_seconds: int

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = ".env",
        *,
        override: bool = False,
    ) -> Settings:
        if env_file:
            load_dotenv(env_file, override=override)

        work_dir = Path(os.getenv("WORK_DIR", "work")).expanduser()
        database_path = Path(os.getenv("DATABASE_PATH", str(work_dir / "jobs.db"))).expanduser()
        channel_config_file = Path(os.getenv("CHANNEL_CONFIG_FILE", "channels.toml")).expanduser()
        channel_config = _read_channel_config(channel_config_file)

        settings = cls(
            ytdlp_cookies_from_browser=os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip().lower(),
            ytdlp_browser_profile=os.getenv("YTDLP_BROWSER_PROFILE", "").strip(),
            ytdlp_cookie_file=(
                Path(os.environ["YTDLP_COOKIE_FILE"].strip()).expanduser()
                if os.getenv("YTDLP_COOKIE_FILE", "").strip()
                else None
            ),
            channel_config_file=channel_config_file,
            youtube_channel_id=(
                os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
                or _nested_string(channel_config, "youtube", "channel_id")
            ),
            youtube_client_secrets_file=Path(
                os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "client_secret.json")
            ).expanduser(),
            youtube_token_file=Path(
                os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")
            ).expanduser(),
            youtube_privacy_status=os.getenv("YOUTUBE_PRIVACY_STATUS", "public").strip().lower(),
            upload_youtube=_bool_env("UPLOAD_YOUTUBE", False),
            instagram_user_id=(
                os.getenv("INSTAGRAM_USER_ID", "").strip()
                or _nested_string(channel_config, "instagram", "user_id")
            ),
            instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip(),
            instagram_graph_api_version=os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v26.0").strip(),
            upload_instagram=_bool_env("UPLOAD_INSTAGRAM", False),
            facebook_page_id=(
                os.getenv("FACEBOOK_PAGE_ID", "").strip()
                or _nested_string(channel_config, "facebook", "page_id")
            ),
            facebook_access_token=(
                os.getenv("FACEBOOK_ACCESS_TOKEN", "").strip()
                or os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
            ),
            facebook_graph_api_version=os.getenv("FACEBOOK_GRAPH_API_VERSION", "v26.0").strip(),
            upload_facebook=_bool_env("UPLOAD_FACEBOOK", True),
            facebook_limit_cooldown_hours=_float_env("FACEBOOK_LIMIT_COOLDOWN_HOURS", 24.0),
            youtube_description_target_chars=_int_env("YOUTUBE_DESCRIPTION_TARGET_CHARS", 4_200),
            instagram_caption_target_chars=_int_env("INSTAGRAM_CAPTION_TARGET_CHARS", 2_000),
            hotclip_watch_dir=Path(
                os.getenv("HOTCLIP_WATCH_DIR", "hotclip-watch")
            ).expanduser(),
            hotclip_export_dir=Path(
                os.getenv("HOTCLIP_EXPORT_DIR", "hotclip-exports")
            ).expanduser(),
            hotclip_min_clip_age_seconds=_int_env("HOTCLIP_MIN_CLIP_AGE_SECONDS", 90),
            channels_file=Path(os.getenv("CHANNELS_FILE", "channels.txt")).expanduser(),
            channel_scan_max_videos=_int_env("CHANNEL_SCAN_MAX_VIDEOS", 5),
            channel_scan_interval_minutes=_int_env("CHANNEL_SCAN_INTERVAL_MINUTES", 60),
            schedule_timezone=os.getenv("SCHEDULE_TIMEZONE", "").strip(),
            youtube_schedule_times=os.getenv("YOUTUBE_SCHEDULE_TIMES", "").strip(),
            instagram_schedule_times=os.getenv("INSTAGRAM_SCHEDULE_TIMES", "").strip(),
            facebook_schedule_times=os.getenv("FACEBOOK_SCHEDULE_TIMES", "").strip(),
            youtube_uploads_per_slot=_int_env("YOUTUBE_UPLOADS_PER_SLOT", 1),
            instagram_uploads_per_slot=_int_env("INSTAGRAM_UPLOADS_PER_SLOT", 1),
            facebook_uploads_per_slot=_int_env("FACEBOOK_UPLOADS_PER_SLOT", 1),
            work_dir=work_dir,
            database_path=database_path,
            delete_uploaded_clips=_bool_env("DELETE_UPLOADED_CLIPS", False),
            rights_acknowledged=_bool_env("RIGHTS_ACKNOWLEDGED", False),
            links_file=Path(os.getenv("LINKS_FILE", "links.txt")).expanduser(),
            downloaded_links_log=Path(
                os.getenv("DOWNLOADED_LINKS_LOG", str(work_dir / "downloaded-links.log"))
            ).expanduser(),
            links_poll_seconds=_int_env("LINKS_POLL_SECONDS", 30),
            hashtags_file=Path(os.getenv("HASHTAGS_FILE", "hashtags.txt")).expanduser(),
            hashtags_enabled=_bool_env("HASHTAGS_ENABLED", True),
            hashtags_youtube_max=_int_env("HASHTAGS_YOUTUBE_MAX", 59),
            hashtags_instagram_max=_int_env("HASHTAGS_INSTAGRAM_MAX", 30),
            hashtags_facebook_max=_int_env("HASHTAGS_FACEBOOK_MAX", 0),
            status_panel_enabled=_bool_env("STATUS_PANEL_ENABLED", True),
            status_panel_host=os.getenv("STATUS_PANEL_HOST", "127.0.0.1").strip()
            or "127.0.0.1",
            status_panel_port=_int_env("STATUS_PANEL_PORT", 8000),
            status_stale_after_seconds=_int_env("STATUS_STALE_AFTER_SECONDS", 120),
        )
        settings.validate_common()
        return settings

    def schedule_spec(self, platform_value: str) -> tuple[str, int]:
        """(schedule string, uploads per slot) for one platform."""
        if platform_value == "YouTube":
            return self.youtube_schedule_times, self.youtube_uploads_per_slot
        if platform_value == "Instagram":
            return self.instagram_schedule_times, self.instagram_uploads_per_slot
        return self.facebook_schedule_times, self.facebook_uploads_per_slot

    @property
    def scheduled_platforms(self) -> tuple[str, ...]:
        platforms: list[str] = []
        for name in ("YouTube", "Instagram", "Facebook"):
            spec, _ = self.schedule_spec(name)
            if spec:
                platforms.append(name)
        return tuple(platforms)

    def enabled_platforms(self) -> list[str]:
        platforms: list[str] = []
        if self.upload_youtube:
            platforms.append("YouTube")
        if self.upload_instagram:
            platforms.append("Instagram")
        if self.upload_facebook:
            platforms.append("Facebook")
        return platforms

    def validate_common(self) -> None:
        import re

        if self.youtube_privacy_status not in {"private", "unlisted", "public"}:
            raise ConfigurationError("YOUTUBE_PRIVACY_STATUS must be private, unlisted, or public.")
        if not re.fullmatch(r"v\d+\.\d+", self.instagram_graph_api_version):
            raise ConfigurationError("INSTAGRAM_GRAPH_API_VERSION must look like v26.0.")
        if not re.fullmatch(r"v\d+\.\d+", self.facebook_graph_api_version):
            raise ConfigurationError("FACEBOOK_GRAPH_API_VERSION must look like v26.0.")
        if not 500 <= self.youtube_description_target_chars <= 4_500:
            raise ConfigurationError(
                "YOUTUBE_DESCRIPTION_TARGET_CHARS must be between 500 and 4500."
            )
        if not 300 <= self.instagram_caption_target_chars <= 2_000:
            raise ConfigurationError(
                "INSTAGRAM_CAPTION_TARGET_CHARS must be between 300 and 2000."
            )
        if not 30 <= self.hotclip_min_clip_age_seconds <= 3_600:
            raise ConfigurationError(
                "HOTCLIP_MIN_CLIP_AGE_SECONDS must be between 30 and 3600."
            )
        if not 1 <= self.channel_scan_max_videos <= 50:
            raise ConfigurationError("CHANNEL_SCAN_MAX_VIDEOS must be between 1 and 50.")
        if not 5 <= self.channel_scan_interval_minutes <= 1_440:
            raise ConfigurationError(
                "CHANNEL_SCAN_INTERVAL_MINUTES must be between 5 and 1440."
            )
        for name, value in (
            ("YOUTUBE_UPLOADS_PER_SLOT", self.youtube_uploads_per_slot),
            ("INSTAGRAM_UPLOADS_PER_SLOT", self.instagram_uploads_per_slot),
            ("FACEBOOK_UPLOADS_PER_SLOT", self.facebook_uploads_per_slot),
        ):
            if not 1 <= value <= 50:
                raise ConfigurationError(f"{name} must be between 1 and 50.")
        if self.schedule_timezone:
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(self.schedule_timezone)
            except Exception as exc:
                raise ConfigurationError(
                    f"SCHEDULE_TIMEZONE is not a valid IANA timezone: "
                    f"{self.schedule_timezone!r} (e.g. Asia/Kolkata)."
                ) from exc
        from .scheduler import parse_schedule_spec

        for name, value in (
            ("YOUTUBE_SCHEDULE_TIMES", self.youtube_schedule_times),
            ("INSTAGRAM_SCHEDULE_TIMES", self.instagram_schedule_times),
            ("FACEBOOK_SCHEDULE_TIMES", self.facebook_schedule_times),
        ):
            try:
                parse_schedule_spec(value)
            except ValueError as exc:
                raise ConfigurationError(f"{name}: {exc}") from exc
        if not 5 <= self.links_poll_seconds <= 3600:
            raise ConfigurationError("LINKS_POLL_SECONDS must be between 5 and 3600.")
        for name, value in (
            ("HASHTAGS_YOUTUBE_MAX", self.hashtags_youtube_max),
            ("HASHTAGS_INSTAGRAM_MAX", self.hashtags_instagram_max),
            ("HASHTAGS_FACEBOOK_MAX", self.hashtags_facebook_max),
        ):
            if not 0 <= value <= 500:
                raise ConfigurationError(f"{name} must be between 0 and 500 (0 = unlimited).")
        if self.hashtags_youtube_max > 59:
            raise ConfigurationError(
                "HASHTAGS_YOUTUBE_MAX above 59 makes YouTube ignore every hashtag "
                "(the uploader adds #Shorts itself; 60 total is the API cap)."
            )
        if self.hashtags_instagram_max > 30:
            raise ConfigurationError(
                "HASHTAGS_INSTAGRAM_MAX above 30 makes Instagram reject the caption."
            )
        if not 1 <= self.status_panel_port <= 65_535:
            raise ConfigurationError("STATUS_PANEL_PORT must be between 1 and 65535.")
        if not 30 <= self.status_stale_after_seconds <= 86_400:
            raise ConfigurationError(
                "STATUS_STALE_AFTER_SECONDS must be between 30 and 86400."
            )
        if (
            self.ytdlp_cookies_from_browser
            and self.ytdlp_cookies_from_browser not in _SUPPORTED_COOKIE_BROWSERS
        ):
            supported = ", ".join(sorted(_SUPPORTED_COOKIE_BROWSERS))
            raise ConfigurationError(f"YTDLP_COOKIES_FROM_BROWSER must be one of: {supported}.")

    def validate_harvest(self) -> None:
        """Light gate for download/discovery-only stages (no platform creds needed)."""
        if not self.rights_acknowledged:
            raise ConfigurationError(
                "Set RIGHTS_ACKNOWLEDGED=true only after confirming you own or "
                "have permission to reuse every submitted video."
            )
        if self.ytdlp_cookie_file and not self.ytdlp_cookie_file.exists():
            raise ConfigurationError(f"YTDLP_COOKIE_FILE was not found: {self.ytdlp_cookie_file}")

    def validate_queue(self) -> None:
        if not self.rights_acknowledged:
            raise ConfigurationError(
                "Set RIGHTS_ACKNOWLEDGED=true only after confirming you own or have "
                "permission to reuse every submitted video."
            )
        if self.ytdlp_cookie_file and not self.ytdlp_cookie_file.exists():
            raise ConfigurationError(f"YTDLP_COOKIE_FILE was not found: {self.ytdlp_cookie_file}")
        if self.upload_youtube:
            if not self.youtube_channel_id:
                raise ConfigurationError(
                    f"Add your YouTube channel_id to {self.channel_config_file}."
                )
            if not self.youtube_token_file.exists():
                raise ConfigurationError(
                    f"YouTube OAuth token not found at {self.youtube_token_file}. "
                    "Run python -m shorts_bot.youtube_auth first."
                )
        if self.upload_instagram:
            if not self.instagram_user_id:
                raise ConfigurationError(
                    f"Add your Instagram professional account user_id to "
                    f"{self.channel_config_file}."
                )
            if not self.instagram_user_id.isdigit():
                raise ConfigurationError(
                    "Instagram user_id must be the numeric Professional Account ID returned by "
                    "instagram_business_account.id, not a username or Business Portfolio name."
                )
            if not self.instagram_access_token:
                raise ConfigurationError(
                    "INSTAGRAM_ACCESS_TOKEN is required for Instagram publishing."
                )
        if self.upload_facebook:
            if not self.facebook_page_id:
                raise ConfigurationError(
                    f"Add your numeric Facebook page_id to {self.channel_config_file}."
                )
            if not self.facebook_page_id.isdigit():
                raise ConfigurationError("Facebook page_id must be numeric, not a Page name.")
            if not self.facebook_access_token:
                raise ConfigurationError(
                    "FACEBOOK_ACCESS_TOKEN is required, or leave it blank to reuse "
                    "INSTAGRAM_ACCESS_TOKEN."
                )
        if not self.upload_youtube and not self.upload_instagram and not self.upload_facebook:
            raise ConfigurationError(
                "Enable UPLOAD_YOUTUBE, UPLOAD_INSTAGRAM, or UPLOAD_FACEBOOK."
            )

    def quota_warnings(self) -> list[str]:
        """Heads-up messages when configured volume exceeds default platform ceilings."""
        from .scheduler import parse_schedule_spec

        warnings: list[str] = []
        if self.upload_youtube and self.youtube_schedule_times:
            schedule = parse_schedule_spec(self.youtube_schedule_times)
            weekly_slots = sum(len(times) for times in schedule.values())
            days_with_slots = sum(1 for times in schedule.values() if times)
            per_week = weekly_slots * self.youtube_uploads_per_slot
            daily_average = per_week / 7 if days_with_slots else 0
            if daily_average > 6:
                warnings.append(
                    f"YouTube is configured for up to {daily_average:g} uploads/day. The default "
                    "YouTube Data API quota (10,000 units) fits only ~6/day; extra uploads will "
                    "fail with quota errors and catch up on later days. Request a quota "
                    "increase in Google Cloud Console to sustain this volume."
                )
        return warnings

    def prepare_directories(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)
        self.links_file.parent.mkdir(parents=True, exist_ok=True)
        self.links_file.touch(exist_ok=True)
        self.downloaded_links_log.parent.mkdir(parents=True, exist_ok=True)
        self.hotclip_watch_dir.mkdir(parents=True, exist_ok=True)
        self.hotclip_export_dir.mkdir(parents=True, exist_ok=True)
