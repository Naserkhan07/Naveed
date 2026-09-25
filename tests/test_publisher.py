from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shorts_bot.config import Settings
from shorts_bot.db import JobRepository
from shorts_bot.errors import UploadLimitError
from shorts_bot.models import ChannelPlatform, InstagramUploadResult, ShortPlan
from shorts_bot.publisher import Publisher


class FakeMedia:
    def probe_duration(self, path: Path) -> float:
        return 30.0


class FakeYouTube:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    async def upload(
        self,
        video_path: Path,
        plan: ShortPlan,
        thumbnail_path: Path | None = None,
    ) -> str:
        assert video_path.read_bytes() == b"clip"
        self.uploads.append(plan.title)
        return f"yt-{len(self.uploads)}"


class FakeInstagram:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
        self.uploads.append(plan.title)
        return InstagramUploadResult(f"ig-{len(self.uploads)}", "https://instagram.com/reel/x")


class LimitFacebook:
    async def upload(self, video_path: Path, plan: ShortPlan) -> tuple[str, str]:
        raise UploadLimitError("Facebook", "Meta limit reached")


def _settings(tmp_path: Path) -> Settings:
    base = Settings.from_env(env_file=None)
    return replace(
        base,
        rights_acknowledged=True,
        upload_youtube=True,
        upload_instagram=True,
        upload_facebook=True,
        youtube_channel_id="UC123",
        instagram_user_id="1789",
        instagram_access_token="token",
        facebook_page_id="123",
        facebook_access_token="token",
        schedule_timezone="UTC",
        work_dir=tmp_path / "work",
        database_path=tmp_path / "work" / "jobs.db",
        hotclip_watch_dir=tmp_path / "watch",
        hotclip_export_dir=tmp_path / "exports",
    )


_UNSET = object()


def _publisher(
    settings: Settings,
    repository: JobRepository,
    youtube=_UNSET,
    instagram=_UNSET,
    facebook=_UNSET,
) -> Publisher:
    return Publisher(
        settings,
        repository,
        media=FakeMedia(),  # type: ignore[arg-type]
        youtube=FakeYouTube() if youtube is _UNSET else youtube,  # type: ignore[arg-type]
        instagram=FakeInstagram() if instagram is _UNSET else instagram,  # type: ignore[arg-type]
        facebook=facebook if facebook is not _UNSET else None,  # type: ignore[arg-type]
    )


def _add_clip(repository: JobRepository, tmp_path: Path, name: str, title: str) -> Path:
    clip = tmp_path / "exports" / name
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip")
    repository.add_publication(clip, title=title, description=f"{title} body")
    return clip


async def test_fifo_order(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = JobRepository(settings.database_path)
    _add_clip(repository, tmp_path, "clip-01.mp4", "First")
    _add_clip(repository, tmp_path, "clip-02.mp4", "Second")

    youtube = FakeYouTube()
    publisher = _publisher(settings, repository, youtube=youtube)
    published = await publisher.publish_platform(ChannelPlatform.YOUTUBE, max_uploads=2)
    assert youtube.uploads == ["First", "Second"]
    assert [pub.youtube_video_id for pub in published] == ["yt-1", "yt-2"]


async def test_publish_platform_not_enabled(tmp_path: Path) -> None:
    settings = replace(_settings(tmp_path), upload_facebook=False)
    repository = JobRepository(settings.database_path)
    publisher = _publisher(settings, repository)
    messages: list[str] = []
    published = await publisher.publish_platform(ChannelPlatform.FACEBOOK, report=messages.append)
    assert published == []
    assert messages and "disabled" in messages[0]


async def test_due_credits_drive_upload_count(tmp_path: Path) -> None:
    settings = replace(
        _settings(tmp_path),
        youtube_schedule_times="00:00",  # one slot already passed today (UTC)
        youtube_uploads_per_slot=7,
    )
    repository = JobRepository(settings.database_path)
    for index in range(3):
        _add_clip(repository, tmp_path, f"clip-{index}.mp4", f"Clip {index}")

    publisher = _publisher(settings, repository)
    published = await publisher.publish_due(ChannelPlatform.YOUTUBE)
    assert len(published) == 3  # only three queued, though 7 owed

    # The DB timestamps consumed the slot credit partially; re-running keeps 4 owed.
    for index in range(4):
        _add_clip(repository, tmp_path, f"clip-9{index}.mp4", f"Catchup {index}")
    published_again = await publisher.publish_due(ChannelPlatform.YOUTUBE)
    assert len(published_again) == 4
    # Slot fully consumed now.
    assert await publisher.publish_due(ChannelPlatform.YOUTUBE) == []


async def test_facebook_limit_pauses_and_keeps_pending(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = JobRepository(settings.database_path)
    _add_clip(repository, tmp_path, "clip.mp4", "Solo")

    publisher = _publisher(settings, repository, facebook=LimitFacebook())
    published = await publisher.publish_platform(
        ChannelPlatform.FACEBOOK,
        max_uploads=5,
    )
    assert published == []
    pending = repository.next_pending_publication(ChannelPlatform.FACEBOOK)
    assert pending is not None  # still queued for the next run


async def test_publish_no_schedule_configured(tmp_path: Path) -> None:
    settings = _settings(tmp_path)  # no schedules set by default
    repository = JobRepository(settings.database_path)
    publisher = _publisher(settings, repository)
    assert await publisher.publish_due(ChannelPlatform.YOUTUBE) == []


async def test_missing_file_marks_error_and_stops(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = JobRepository(settings.database_path)
    ghost = tmp_path / "exports" / "ghost.mp4"
    ghost.parent.mkdir(parents=True, exist_ok=True)
    ghost.write_bytes(b"clip")
    repository.add_publication(ghost, title="Ghost")
    ghost.unlink()

    publisher = _publisher(settings, repository)
    published = await publisher.publish_platform(ChannelPlatform.YOUTUBE, max_uploads=1)
    assert published == []
    publication = repository.list_publications()[0]
    assert publication.error is not None


class FakeFacebook:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    async def upload(self, video_path: Path, plan: ShortPlan) -> tuple[str, str]:
        self.uploads.append(plan.title)
        return "fb-1", "https://www.facebook.com/reel/fb-1"


async def test_cleanup_deletes_clip_when_fully_published(tmp_path: Path) -> None:
    settings = replace(_settings(tmp_path), delete_uploaded_clips=True)
    repository = JobRepository(settings.database_path)
    clip_path = _add_clip(repository, tmp_path, "solo.mp4", "Solo")
    publisher = _publisher(settings, repository, facebook=FakeFacebook())

    await publisher.publish_platform(ChannelPlatform.YOUTUBE, max_uploads=1)
    assert clip_path.exists()  # still waiting for Instagram/Facebook
    await publisher.publish_platform(ChannelPlatform.INSTAGRAM, max_uploads=1)
    assert clip_path.exists()  # still waiting for Facebook
    await publisher.publish_platform(ChannelPlatform.FACEBOOK, max_uploads=1)
    assert not clip_path.exists()  # published everywhere, file cleaned up
