from pathlib import Path

import pytest

from shorts_bot.config import Settings
from shorts_bot.errors import ConfigurationError


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    names = [
        "GROQ_API_KEY",
        "GROQ_MODEL",
        "GROQ_FALLBACK_MODEL",
        "GROQ_MAX_TRANSCRIPT_CHARS",
        "MAX_SHORTS_PER_VIDEO",
        "SHORTS_SELECTION_MODE",
        "VIDEO_LAYOUT",
        "VIDEO_ALLOW_UPSCALE",
        "VIDEO_CRF",
        "VIDEO_PRESET",
        "VIDEO_ENHANCER",
        "APIMARKET_API_KEY",
        "APIMARKET_MAX_CLIPS",
        "CLOUDINARY_CLOUD_NAME",
        "CLOUDINARY_API_KEY",
        "CLOUDINARY_API_SECRET",
        "ARCHIVE_ON_UPLOAD_LIMIT",
        "ARCHIVE_DIR",
        "OPEN_UPLOAD_LIMIT_FOLDER",
        "YOUTUBE_DESCRIPTION_TARGET_CHARS",
        "INSTAGRAM_CAPTION_TARGET_CHARS",
        "INSTAGRAM_HASHTAGS_FILE",
        "INSTAGRAM_CAPTION_MENTIONS",
        "INSTAGRAM_CAPTION_ROTATION_FILE",
        "GROQ_METADATA_DELAY_SECONDS",
        "YTDLP_COOKIES_FROM_BROWSER",
        "YTDLP_BROWSER_PROFILE",
        "YTDLP_COOKIE_FILE",
        "UPLOAD_YOUTUBE",
        "UPLOAD_INSTAGRAM",
        "UPLOAD_FACEBOOK",
        "FACEBOOK_PAGE_ID",
        "FACEBOOK_ACCESS_TOKEN",
        "FACEBOOK_GRAPH_API_VERSION",
        "FACEBOOK_LIMIT_COOLDOWN_HOURS",
        "AUTO_UPLOAD",
        "CLIP_DURATION_SECONDS",
        "WORK_DIR",
        "DATABASE_PATH",
        "KEEP_WORK_FILES",
        "CREDENTIAL_CHECK_MINUTES",
        "PENDING_RETRY_JOBS_PER_CYCLE",
        "RIGHTS_ACKNOWLEDGED",
        "YOUTUBE_PRIVACY_STATUS",
        "CHANNEL_CONFIG_FILE",
        "INSTAGRAM_ACCESS_TOKEN",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_reads_valid_local_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("RIGHTS_ACKNOWLEDGED", "true")
    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("CHANNEL_CONFIG_FILE", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "123456")
    monkeypatch.setenv("FACEBOOK_ACCESS_TOKEN", "page-token")

    settings = Settings.from_env(env_file=None)
    settings.validate_pipeline()

    assert settings.clip_duration_seconds == 30
    assert settings.groq_model == "qwen/qwen3.6-27b"
    assert settings.groq_max_transcript_chars == 8_000
    assert settings.shorts_selection_mode == "full_coverage"
    assert settings.max_shorts_per_video == 0
    assert settings.video_layout == "fit_black"
    assert settings.video_allow_upscale is False
    assert settings.video_crf == 18
    assert settings.video_preset == "slow"
    assert settings.video_enhancer == "none"
    assert settings.apimarket_max_clips == 5
    assert settings.archive_on_upload_limit is True
    assert settings.archive_dir == tmp_path / "work" / "pending_uploads"
    assert settings.open_upload_limit_folder is True
    assert settings.youtube_description_target_chars == 4_200
    assert settings.instagram_caption_target_chars == 2_000
    assert settings.instagram_mentions() == ["@wzz.unfiltered", "@precious.tulip1"]
    assert settings.upload_youtube is False
    assert settings.upload_instagram is False
    assert settings.upload_facebook is True
    assert settings.facebook_page_id == "123456"
    assert settings.facebook_access_token == "page-token"
    assert settings.facebook_graph_api_version == "v26.0"
    assert settings.facebook_limit_cooldown_hours == 24.0
    assert settings.youtube_privacy_status == "public"
    assert settings.credential_check_minutes == 60
    assert settings.pending_retry_jobs_per_cycle == 3


def test_migrates_retired_groq_models_to_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "llama-3.3-70b-versatile")

    settings = Settings.from_env(env_file=None)

    assert settings.groq_model == "qwen/qwen3.6-27b"
    assert settings.groq_fallback_model == "qwen/qwen3.6-27b"


def test_reads_non_secret_ids_from_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_file = tmp_path / "channels.toml"
    config_file.write_text(
        '[youtube]\nchannel_id = "UC123"\n[instagram]\nuser_id = "1789"\n'
        '[facebook]\npage_id = "123"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_CONFIG_FILE", str(config_file))

    settings = Settings.from_env(env_file=None)

    assert settings.youtube_channel_id == "UC123"
    assert settings.instagram_user_id == "1789"
    assert settings.facebook_page_id == "123"


def test_reads_browser_cookie_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CHANNEL_CONFIG_FILE", str(tmp_path / "missing.toml"))
    cookie_file = tmp_path / "youtube-cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "BRAVE")
    monkeypatch.setenv("YTDLP_BROWSER_PROFILE", "Profile 1")
    monkeypatch.setenv("YTDLP_COOKIE_FILE", str(cookie_file))

    settings = Settings.from_env(env_file=None)

    assert settings.ytdlp_cookies_from_browser == "brave"
    assert settings.ytdlp_browser_profile == "Profile 1"
    assert settings.ytdlp_cookie_file == cookie_file


def test_rejects_duration_outside_shorts_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIP_DURATION_SECONDS", "31")

    with pytest.raises(ConfigurationError, match="between 20 and 30"):
        Settings.from_env(env_file=None)


def test_rejects_instagram_username_instead_of_numeric_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "channels.toml"
    config_file.write_text(
        '[youtube]\nchannel_id = ""\n[instagram]\nuser_id = "my.username"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("UPLOAD_INSTAGRAM", "true")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "token")
    monkeypatch.setenv("GROQ_API_KEY", "key")
    monkeypatch.setenv("RIGHTS_ACKNOWLEDGED", "true")
    settings = Settings.from_env(env_file=None)

    with pytest.raises(ConfigurationError, match="numeric Professional Account ID"):
        settings.validate_pipeline()


def test_api_market_enhancer_requires_private_hosting_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "key")
    monkeypatch.setenv("RIGHTS_ACKNOWLEDGED", "true")
    monkeypatch.setenv("VIDEO_ENHANCER", "api_market")
    settings = Settings.from_env(env_file=None)

    with pytest.raises(ConfigurationError, match="APIMARKET_API_KEY"):
        settings.validate_pipeline()


def test_requires_rights_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "key")
    settings = Settings.from_env(env_file=None)

    with pytest.raises(ConfigurationError, match="RIGHTS_ACKNOWLEDGED"):
        settings.validate_pipeline()
