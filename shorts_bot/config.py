from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .errors import ConfigurationError

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}
_SCHEDULE_TIMES_RE = re.compile(
    r"^(?:[01]\d|2[0-3]):[0-5]\d(?:\s*,\s*(?:[01]\d|2[0-3]):[0-5]\d)*$"
)


def _validate_schedule_times(name: str, value: str) -> None:
    if not value:
        return
    if not _SCHEDULE_TIMES_RE.fullmatch(value):
        raise ConfigurationError(
            f"{name} must be comma-separated 24-hour times like 09:30,18:00."
        )
_DEFAULT_GROQ_MODEL = "qwen/qwen3.6-27b"
_DEPRECATED_GROQ_MODELS = {
    "llama-3.1-8b-instant": _DEFAULT_GROQ_MODEL,
    "llama-3.3-70b-versatile": _DEFAULT_GROQ_MODEL,
}
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


def _groq_model_env(name: str) -> str:
    configured = os.getenv(name, _DEFAULT_GROQ_MODEL).strip()
    return _DEPRECATED_GROQ_MODELS.get(configured, configured)


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
    groq_api_key: str
    groq_model: str
    groq_fallback_model: str
    groq_transcription_model: str
    groq_max_transcript_chars: int
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
    instagram_hashtags_file: Path
    instagram_caption_mentions: str
    instagram_caption_rotation_file: Path
    upload_instagram: bool
    facebook_page_id: str
    facebook_access_token: str
    facebook_graph_api_version: str
    upload_facebook: bool
    facebook_limit_cooldown_hours: float
    youtube_description_target_chars: int
    instagram_caption_target_chars: int
    groq_metadata_delay_seconds: int
    clip_duration_seconds: int
    shorts_selection_mode: str
    max_shorts_per_video: int
    video_layout: str
    video_allow_upscale: bool
    video_crf: int
    video_preset: str
    video_enhancer: str
    apimarket_api_key: str
    apimarket_base_url: str
    apimarket_version: str
    apimarket_model: str
    apimarket_resolution: str
    apimarket_max_clips: int
    apimarket_timeout_seconds: int
    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_api_secret: str
    archive_on_upload_limit: bool
    archive_dir: Path
    open_upload_limit_folder: bool
    work_dir: Path
    database_path: Path
    keep_work_files: bool
    delete_uploaded_clips: bool
    subtitles_enabled: bool
    subtitles_words_per_screen: int
    subtitles_font_size: int
    subtitles_position_y: int
    subtitles_font_name: str
    subtitles_font_dir: Path
    channels_file: Path
    channel_scan_max_videos: int
    channel_scan_interval_minutes: int
    schedule_timezone: str
    youtube_schedule_times: str
    instagram_schedule_times: str
    facebook_schedule_times: str
    rights_acknowledged: bool
    links_file: Path
    downloaded_links_log: Path
    links_poll_seconds: int
    credential_check_minutes: int
    pending_retry_jobs_per_cycle: int

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
        legacy_auto_upload = _bool_env("AUTO_UPLOAD", False)

        settings = cls(
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            groq_model=_groq_model_env("GROQ_MODEL"),
            groq_fallback_model=_groq_model_env("GROQ_FALLBACK_MODEL"),
            groq_transcription_model=os.getenv(
                "GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo"
            ).strip(),
            groq_max_transcript_chars=_int_env("GROQ_MAX_TRANSCRIPT_CHARS", 8_000),
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
            upload_youtube=_bool_env("UPLOAD_YOUTUBE", legacy_auto_upload),
            instagram_user_id=(
                os.getenv("INSTAGRAM_USER_ID", "").strip()
                or _nested_string(channel_config, "instagram", "user_id")
            ),
            instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip(),
            instagram_graph_api_version=os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v26.0").strip(),
            instagram_hashtags_file=Path(
                os.getenv("INSTAGRAM_HASHTAGS_FILE", "instagram_hashtags.txt")
            ).expanduser(),
            instagram_caption_mentions=os.getenv(
                "INSTAGRAM_CAPTION_MENTIONS",
                "@wzz.unfiltered @precious.tulip1",
            ).strip(),
            instagram_caption_rotation_file=Path(
                os.getenv("INSTAGRAM_CAPTION_ROTATION_FILE", "instagram_captions.txt")
            ).expanduser(),
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
            groq_metadata_delay_seconds=_int_env("GROQ_METADATA_DELAY_SECONDS", 30),
            clip_duration_seconds=_int_env("CLIP_DURATION_SECONDS", 30),
            shorts_selection_mode=os.getenv("SHORTS_SELECTION_MODE", "full_coverage")
            .strip()
            .lower(),
            max_shorts_per_video=_int_env("MAX_SHORTS_PER_VIDEO", 0),
            video_layout=os.getenv("VIDEO_LAYOUT", "fit_black").strip().lower(),
            video_allow_upscale=_bool_env("VIDEO_ALLOW_UPSCALE", False),
            video_crf=_int_env("VIDEO_CRF", 18),
            video_preset=os.getenv("VIDEO_PRESET", "slow").strip().lower(),
            video_enhancer=os.getenv("VIDEO_ENHANCER", "none").strip().lower(),
            apimarket_api_key=os.getenv("APIMARKET_API_KEY", "").strip(),
            apimarket_base_url=os.getenv(
                "APIMARKET_BASE_URL",
                "https://prod.api.market/api/v1/magicapi/video-upscaler-high-resolution-api",
            )
            .strip()
            .rstrip("/"),
            apimarket_version=os.getenv(
                "APIMARKET_VERSION",
                "c23768236472c41b7a121ee735c8073e29080c01b32907740cfada61bff75320",
            ).strip(),
            apimarket_model=os.getenv("APIMARKET_MODEL", "RealESRGAN_x4plus").strip(),
            apimarket_resolution=os.getenv("APIMARKET_RESOLUTION", "FHD").strip(),
            apimarket_max_clips=_int_env("APIMARKET_MAX_CLIPS", 5),
            apimarket_timeout_seconds=_int_env("APIMARKET_TIMEOUT_SECONDS", 1_200),
            cloudinary_cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", "").strip(),
            cloudinary_api_key=os.getenv("CLOUDINARY_API_KEY", "").strip(),
            cloudinary_api_secret=os.getenv("CLOUDINARY_API_SECRET", "").strip(),
            archive_on_upload_limit=_bool_env("ARCHIVE_ON_UPLOAD_LIMIT", True),
            archive_dir=Path(
                os.getenv("ARCHIVE_DIR", str(work_dir / "pending_uploads"))
            ).expanduser(),
            open_upload_limit_folder=_bool_env("OPEN_UPLOAD_LIMIT_FOLDER", True),
            work_dir=work_dir,
            database_path=database_path,
            keep_work_files=_bool_env("KEEP_WORK_FILES", True),
            delete_uploaded_clips=_bool_env("DELETE_UPLOADED_CLIPS", True),
            subtitles_enabled=_bool_env("SUBTITLES_ENABLED", True),
            subtitles_words_per_screen=_int_env("SUBTITLES_WORDS_PER_SCREEN", 4),
            subtitles_font_size=_int_env("SUBTITLES_FONT_SIZE", 62),
            subtitles_position_y=_int_env("SUBTITLES_POSITION_Y", 850),
            subtitles_font_name=os.getenv("SUBTITLES_FONT_NAME", "Anton").strip() or "Anton",
            subtitles_font_dir=Path(
                os.getenv("SUBTITLES_FONT_DIR", "fonts")
            ).expanduser(),
            channels_file=Path(os.getenv("CHANNELS_FILE", "channels.txt")).expanduser(),
            channel_scan_max_videos=_int_env("CHANNEL_SCAN_MAX_VIDEOS", 5),
            channel_scan_interval_minutes=_int_env("CHANNEL_SCAN_INTERVAL_MINUTES", 60),
            schedule_timezone=os.getenv("SCHEDULE_TIMEZONE", "").strip(),
            youtube_schedule_times=os.getenv("YOUTUBE_SCHEDULE_TIMES", "").strip(),
            instagram_schedule_times=os.getenv("INSTAGRAM_SCHEDULE_TIMES", "").strip(),
            facebook_schedule_times=os.getenv("FACEBOOK_SCHEDULE_TIMES", "").strip(),
            rights_acknowledged=_bool_env("RIGHTS_ACKNOWLEDGED", False),
            links_file=Path(os.getenv("LINKS_FILE", "links.txt")).expanduser(),
            downloaded_links_log=Path(
                os.getenv("DOWNLOADED_LINKS_LOG", str(work_dir / "downloaded-links.log"))
            ).expanduser(),
            links_poll_seconds=_int_env("LINKS_POLL_SECONDS", 30),
            credential_check_minutes=_int_env("CREDENTIAL_CHECK_MINUTES", 60),
            pending_retry_jobs_per_cycle=_int_env("PENDING_RETRY_JOBS_PER_CYCLE", 3),
        )
        settings.validate_common()
        return settings

    def validate_common(self) -> None:
        if not 4_000 <= self.groq_max_transcript_chars <= 60_000:
            raise ConfigurationError("GROQ_MAX_TRANSCRIPT_CHARS must be between 4000 and 60000.")
        if not 20 <= self.clip_duration_seconds <= 30:
            raise ConfigurationError("CLIP_DURATION_SECONDS must be between 20 and 30.")
        if self.shorts_selection_mode not in {"full_coverage", "ai_highlights"}:
            raise ConfigurationError(
                "SHORTS_SELECTION_MODE must be full_coverage or ai_highlights."
            )
        if not 0 <= self.max_shorts_per_video <= 100:
            raise ConfigurationError("MAX_SHORTS_PER_VIDEO must be between 0 and 100.")
        if self.video_layout not in {"fit_black", "blurred_background", "center_crop"}:
            raise ConfigurationError(
                "VIDEO_LAYOUT must be fit_black, blurred_background, or center_crop."
            )
        if not 14 <= self.video_crf <= 28:
            raise ConfigurationError("VIDEO_CRF must be between 14 and 28.")
        if self.video_preset not in {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        }:
            raise ConfigurationError("VIDEO_PRESET is not a supported x264 preset.")
        if self.video_enhancer not in {"none", "api_market"}:
            raise ConfigurationError("VIDEO_ENHANCER must be none or api_market.")
        if not 0 <= self.apimarket_max_clips <= 100:
            raise ConfigurationError("APIMARKET_MAX_CLIPS must be between 0 and 100.")
        if not 60 <= self.apimarket_timeout_seconds <= 7_200:
            raise ConfigurationError("APIMARKET_TIMEOUT_SECONDS must be between 60 and 7200.")
        if not 500 <= self.youtube_description_target_chars <= 4_500:
            raise ConfigurationError(
                "YOUTUBE_DESCRIPTION_TARGET_CHARS must be between 500 and 4500."
            )
        if not 300 <= self.instagram_caption_target_chars <= 2_000:
            raise ConfigurationError("INSTAGRAM_CAPTION_TARGET_CHARS must be between 300 and 2000.")
        if not 0 <= self.groq_metadata_delay_seconds <= 120:
            raise ConfigurationError("GROQ_METADATA_DELAY_SECONDS must be between 0 and 120.")
        if self.youtube_privacy_status not in {"private", "unlisted", "public"}:
            raise ConfigurationError("YOUTUBE_PRIVACY_STATUS must be private, unlisted, or public.")
        if not re.fullmatch(r"v\d+\.\d+", self.instagram_graph_api_version):
            raise ConfigurationError("INSTAGRAM_GRAPH_API_VERSION must look like v26.0.")
        if not re.fullmatch(r"v\d+\.\d+", self.facebook_graph_api_version):
            raise ConfigurationError("FACEBOOK_GRAPH_API_VERSION must look like v26.0.")
        if not 5 <= self.links_poll_seconds <= 3600:
            raise ConfigurationError("LINKS_POLL_SECONDS must be between 5 and 3600.")
        if not 5 <= self.credential_check_minutes <= 1_440:
            raise ConfigurationError("CREDENTIAL_CHECK_MINUTES must be between 5 and 1440.")
        if not 1 <= self.pending_retry_jobs_per_cycle <= 20:
            raise ConfigurationError("PENDING_RETRY_JOBS_PER_CYCLE must be between 1 and 20.")
        if not 1 <= self.subtitles_words_per_screen <= 8:
            raise ConfigurationError("SUBTITLES_WORDS_PER_SCREEN must be between 1 and 8.")
        if not 24 <= self.subtitles_font_size <= 140:
            raise ConfigurationError("SUBTITLES_FONT_SIZE must be between 24 and 140.")
        if not 0 <= self.subtitles_position_y <= 1920:
            raise ConfigurationError("SUBTITLES_POSITION_Y must be between 0 and 1920.")
        if not 1 <= self.channel_scan_max_videos <= 50:
            raise ConfigurationError("CHANNEL_SCAN_MAX_VIDEOS must be between 1 and 50.")
        if not 5 <= self.channel_scan_interval_minutes <= 1_440:
            raise ConfigurationError(
                "CHANNEL_SCAN_INTERVAL_MINUTES must be between 5 and 1440."
            )
        if self.schedule_timezone:
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(self.schedule_timezone)
            except Exception as exc:
                raise ConfigurationError(
                    f"SCHEDULE_TIMEZONE is not a valid IANA timezone: "
                    f"{self.schedule_timezone!r} (e.g. Asia/Kolkata)."
                ) from exc
        for name, value in (
            ("YOUTUBE_SCHEDULE_TIMES", self.youtube_schedule_times),
            ("INSTAGRAM_SCHEDULE_TIMES", self.instagram_schedule_times),
            ("FACEBOOK_SCHEDULE_TIMES", self.facebook_schedule_times),
        ):
            _validate_schedule_times(name, value)
        if (
            self.ytdlp_cookies_from_browser
            and self.ytdlp_cookies_from_browser not in _SUPPORTED_COOKIE_BROWSERS
        ):
            supported = ", ".join(sorted(_SUPPORTED_COOKIE_BROWSERS))
            raise ConfigurationError(f"YTDLP_COOKIES_FROM_BROWSER must be one of: {supported}.")

    @property
    def youtube_upload_immediate(self) -> bool:
        """Upload to YouTube right after rendering unless a schedule is configured."""
        return not self.youtube_schedule_times

    @property
    def instagram_upload_immediate(self) -> bool:
        return not self.instagram_schedule_times

    @property
    def facebook_upload_immediate(self) -> bool:
        return not self.facebook_schedule_times

    @property
    def scheduled_platforms(self) -> tuple[str, ...]:
        platforms: list[str] = []
        if self.upload_youtube and self.youtube_schedule_times:
            platforms.append("YouTube")
        if self.upload_instagram and self.instagram_schedule_times:
            platforms.append("Instagram")
        if self.upload_facebook and self.facebook_schedule_times:
            platforms.append("Facebook")
        return tuple(platforms)

    def validate_pipeline(self) -> None:
        if not self.rights_acknowledged:
            raise ConfigurationError(
                "Set RIGHTS_ACKNOWLEDGED=true only after confirming you own or have "
                "permission to reuse every submitted video."
            )
        if not self.groq_api_key:
            raise ConfigurationError("GROQ_API_KEY is required for AI clip planning.")
        if self.ytdlp_cookie_file and not self.ytdlp_cookie_file.exists():
            raise ConfigurationError(f"YTDLP_COOKIE_FILE was not found: {self.ytdlp_cookie_file}")
        if self.ytdlp_cookie_file:
            try:
                with self.ytdlp_cookie_file.open(encoding="utf-8") as cookie_file:
                    first_line = cookie_file.readline().strip()
            except OSError as exc:
                raise ConfigurationError(
                    f"Could not read YTDLP_COOKIE_FILE: {self.ytdlp_cookie_file}"
                ) from exc
            if not first_line.startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")):
                raise ConfigurationError(
                    "YTDLP_COOKIE_FILE must be a Netscape-format cookie export."
                )
        if self.video_enhancer == "api_market":
            missing = [
                name
                for name, value in (
                    ("APIMARKET_API_KEY", self.apimarket_api_key),
                    ("CLOUDINARY_CLOUD_NAME", self.cloudinary_cloud_name),
                    ("CLOUDINARY_API_KEY", self.cloudinary_api_key),
                    ("CLOUDINARY_API_SECRET", self.cloudinary_api_secret),
                )
                if not value
            ]
            if missing:
                raise ConfigurationError(
                    "Missing API.market enhancer configuration: " + ", ".join(missing)
                )
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

    def validate_file_queue(self) -> None:
        self.validate_pipeline()
        if not self.upload_youtube and not self.upload_instagram and not self.upload_facebook:
            raise ConfigurationError(
                "Enable UPLOAD_YOUTUBE, UPLOAD_INSTAGRAM, or UPLOAD_FACEBOOK for the "
                "automated link queue."
            )

    def instagram_hashtags(self) -> list[str]:
        if not self.instagram_hashtags_file.exists():
            return []
        text = self.instagram_hashtags_file.read_text(encoding="utf-8")
        tags: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"#[\w]+", text, flags=re.UNICODE):
            normalized = token.casefold()
            if normalized not in seen:
                tags.append(token)
                seen.add(normalized)
        return tags

    def instagram_mentions(self) -> list[str]:
        mentions: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"@[\w.]+", self.instagram_caption_mentions, flags=re.UNICODE):
            normalized = token.casefold()
            if normalized not in seen:
                mentions.append(token)
                seen.add(normalized)
        return mentions

    def instagram_caption_rotation(self) -> list[str]:
        if not self.instagram_caption_rotation_file.exists():
            return []
        return [
            line.strip()
            for line in self.instagram_caption_rotation_file.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

    def prepare_directories(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)
        self.links_file.parent.mkdir(parents=True, exist_ok=True)
        self.links_file.touch(exist_ok=True)
        self.downloaded_links_log.parent.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
