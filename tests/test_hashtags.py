from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from shorts_bot.config import Settings
from shorts_bot.db import JobRepository
from shorts_bot.errors import ConfigurationError
from shorts_bot.hashtags import (
    apply_hashtags,
    count_hashtags,
    load_hashtags,
    parse_hashtag_text,
    plan_with_hashtags,
)
from shorts_bot.models import ChannelPlatform, ShortPlan
from shorts_bot.publisher import Publisher

REPO_ROOT = Path(__file__).resolve().parents[1]

_TAG_ENV = (
    "HASHTAGS_FILE",
    "HASHTAGS_ENABLED",
    "HASHTAGS_YOUTUBE_MAX",
    "HASHTAGS_INSTAGRAM_MAX",
    "HASHTAGS_FACEBOOK_MAX",
)


@pytest.fixture(autouse=True)
def _clean_tag_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _TAG_ENV:
        monkeypatch.delenv(name, raising=False)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base = Settings.from_env(env_file=None)
    return replace(base, hashtags_file=tmp_path / "hashtags.txt", **overrides)  # type: ignore[arg-type]


def _write_tags(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "hashtags.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _plan(**overrides: object) -> ShortPlan:
    base = ShortPlan(
        start_seconds=0.0,
        duration_seconds=30.0,
        title="Clip title",
        description="Clip title body",
        instagram_caption="Clip title body",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_repo_hashtag_file_holds_the_required_ordered_block() -> None:
    tags = load_hashtags(REPO_ROOT / "hashtags.txt")
    assert len(tags) == 207
    assert tags[0] == "#viral"
    assert tags[13] == "#world"
    assert tags[14] == "#afghanistan"
    assert tags[-1] == "#zimbabwe"
    assert len({tag.casefold() for tag in tags}) == len(tags)
    countries = tags[14:]
    assert countries == sorted(countries)


def test_parse_collects_only_hashtags_in_order_without_duplicates() -> None:
    raw = "Comment line, no tags here.\n#One #two, #three! #ONE\nplain text #four\n"
    assert parse_hashtag_text(raw) == ["#One", "#two", "#three", "#four"]


def test_missing_file_means_no_block(tmp_path: Path) -> None:
    plan = _plan()
    settings = _settings(tmp_path)
    assert plan_with_hashtags(plan, ChannelPlatform.YOUTUBE, settings) == plan


def test_disabled_setting_returns_plan_untouched(tmp_path: Path) -> None:
    _write_tags(tmp_path, "#alpha #beta\n")
    settings = _settings(tmp_path, hashtags_enabled=False)
    plan = _plan()
    assert plan_with_hashtags(plan, ChannelPlatform.INSTAGRAM, settings) == plan


def test_instagram_total_stays_within_thirty_with_existing_tags(tmp_path: Path) -> None:
    caption = "Some reel #ClipTag #Another"
    tags = [f"#tag{i:02d}" for i in range(40)]
    result = apply_hashtags(caption, ChannelPlatform.INSTAGRAM, tags, cap=30)
    assert result.startswith("Some reel #ClipTag #Another\n\n#tag00")
    assert count_hashtags(result) == 30  # 2 pre-existing + 28 appended
    assert len(result) <= 2_200


def test_youtube_leaves_room_for_the_uploaders_shorts_tag(tmp_path: Path) -> None:
    tags = [f"#tag{i:02d}" for i in range(100)]
    result = apply_hashtags("Body", ChannelPlatform.YOUTUBE, tags, cap=59)
    assert count_hashtags(result) == 59
    # The uploader appends "\n\n#Shorts"; the API allows 60 total.
    final = f"{result}\n\n#Shorts"
    assert count_hashtags(final) == 60
    assert len(result) <= 4_950


def test_youtube_cap_is_a_total_ceiling(tmp_path: Path) -> None:
    tags = [f"#tag{i:02d}" for i in range(100)]
    base = "Body " + " ".join(f"#pre{i}" for i in range(59))
    result = apply_hashtags(base, ChannelPlatform.YOUTUBE, tags, cap=59)
    assert count_hashtags(result) == 59


def test_facebook_gets_the_full_unlimited_block(tmp_path: Path) -> None:
    tags = load_hashtags(REPO_ROOT / "hashtags.txt")
    result = apply_hashtags("Great clip!", ChannelPlatform.FACEBOOK, tags, cap=0)
    assert count_hashtags(result) == 207
    assert result.startswith("Great clip!\n\n#viral")
    assert result.endswith("#zimbabwe")
    assert len(result) <= 60_000


def test_tags_already_in_text_are_never_duplicated(tmp_path: Path) -> None:
    result = apply_hashtags(
        "Watched #Viral yesterday",
        ChannelPlatform.FACEBOOK,
        ["#viral", "#fresh"],
        cap=0,
    )
    assert result.lower().count("#viral") == 1
    assert result.endswith("#fresh")


def test_character_budget_trims_from_the_end_only(tmp_path: Path) -> None:
    base = "word " * 1_000
    tags = [f"#tag{i:02d}" for i in range(60)]
    result = apply_hashtags(base, ChannelPlatform.INSTAGRAM, tags, cap=30)
    assert len(result) <= 2_200
    assert count_hashtags(result) < 30
    # Every kept block line still follows base order (trimmed from the end).
    appended = result.rsplit("\n\n", 1)[-1].split()
    assert appended == [tag for tag in tags[: len(appended)]]


def test_plan_builder_touches_only_the_field_the_platform_reads(tmp_path: Path) -> None:
    _write_tags(tmp_path, "#alpha #beta #gamma")
    settings = _settings(tmp_path)
    plan = _plan(description="desc body", instagram_caption="cap body")

    youtube = plan_with_hashtags(plan, ChannelPlatform.YOUTUBE, settings)
    assert youtube.description.endswith("#alpha #beta #gamma")
    assert youtube.instagram_caption == "cap body"

    instagram = plan_with_hashtags(plan, ChannelPlatform.INSTAGRAM, settings)
    assert instagram.instagram_caption.endswith("#alpha #beta #gamma")
    assert instagram.description == "desc body"

    facebook = plan_with_hashtags(plan, ChannelPlatform.FACEBOOK, settings)
    assert facebook.description.endswith("#alpha #beta #gamma")


def test_env_defaults_match_platform_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings.from_env(env_file=None)
    assert settings.hashtags_enabled is True
    assert settings.hashtags_youtube_max == 59
    assert settings.hashtags_instagram_max == 30
    assert settings.hashtags_facebook_max == 0
    assert settings.hashtags_file == Path("hashtags.txt")


def test_caps_above_platform_rules_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HASHTAGS_YOUTUBE_MAX", "60")
    with pytest.raises(ConfigurationError, match="HASHTAGS_YOUTUBE_MAX"):
        Settings.from_env(env_file=None)
    monkeypatch.setenv("HASHTAGS_YOUTUBE_MAX", "59")
    monkeypatch.setenv("HASHTAGS_INSTAGRAM_MAX", "31")
    with pytest.raises(ConfigurationError, match="HASHTAGS_INSTAGRAM_MAX"):
        Settings.from_env(env_file=None)


class _FakeMedia:
    def probe_duration(self, path: Path) -> float:
        return 30.0


class _CapturingYouTube:
    def __init__(self) -> None:
        self.plans: list[ShortPlan] = []

    async def upload(
        self, video_path: Path, plan: ShortPlan, thumbnail_path: Path | None = None
    ) -> str:
        self.plans.append(plan)
        return "yt-1"


async def test_publisher_sends_the_hashtag_block(tmp_path: Path) -> None:
    tag_file = _write_tags(tmp_path, "#alpha #beta #gamma #delta")
    settings = replace(
        _settings(tmp_path),
        hashtags_file=tag_file,
        rights_acknowledged=True,
        work_dir=tmp_path / "work",
        database_path=tmp_path / "work" / "jobs.db",
    )
    repository = JobRepository(settings.database_path)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"clip")
    repository.add_publication(clip, title="My clip", description="My clip body")

    youtube = _CapturingYouTube()
    publisher = Publisher(
        settings,
        repository,
        media=_FakeMedia(),  # type: ignore[arg-type]
        youtube=youtube,  # type: ignore[arg-type]
        instagram=None,  # type: ignore[arg-type]
        facebook=None,  # type: ignore[arg-type]
    )
    published = await publisher.publish_platform(ChannelPlatform.YOUTUBE, max_uploads=1)
    assert len(published) == 1
    description = youtube.plans[0].description
    assert description.startswith("My clip body\n\n#alpha #beta #gamma #delta")
    assert count_hashtags(description) == 4
