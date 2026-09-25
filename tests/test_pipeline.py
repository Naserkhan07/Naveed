from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shorts_bot.config import Settings
from shorts_bot.db import JobRepository
from shorts_bot.errors import UploadError, UploadLimitError
from shorts_bot.models import (
    InstagramUploadResult,
    JobStatus,
    ShortPlan,
    SourceVideo,
    WordCue,
)
from shorts_bot.pipeline import WorkflowPipeline, WorkflowServices


class FakeDownloader:
    async def download(self, url: str, destination: Path) -> SourceVideo:
        destination.mkdir(parents=True, exist_ok=True)
        source_path = destination / "source.mp4"
        source_path.write_bytes(b"source")
        return SourceVideo(source_path, url, "id", "Source title", "Creator", 90)


class FakeMedia:
    def probe_duration(self, source: Path) -> float:
        return 90

    def extract_audio(self, source: Path, output: Path) -> Path:
        output.write_bytes(b"audio")
        return output

    def generate_thumbnail(self, video: Path, output: Path, at_seconds: float) -> Path:
        output.write_bytes(b"thumbnail")
        return output

    def render_short(
        self, source: Path, output: Path, start_seconds: float, duration_seconds: float
    ) -> Path:
        assert start_seconds == 10
        assert duration_seconds == 25
        output.write_bytes(b"rendered")
        return output


class FakePlanner:
    async def create_plan(self, audio_path: Path, source: SourceVideo) -> ShortPlan:
        assert audio_path.exists()
        return ShortPlan(
            10,
            25,
            "Short title #Shorts",
            "Description #Shorts",
            "Instagram caption #Reels",
        )

    async def create_plans(
        self,
        audio_path: Path,
        source: SourceVideo,
        max_clips: int,
    ) -> list[ShortPlan]:
        return [await self.create_plan(audio_path, source)]

    async def create_full_coverage_plans(
        self,
        audio_path: Path,
        source: SourceVideo,
        max_clips: int,
    ) -> list[ShortPlan]:
        return await self.create_plans(audio_path, source, max_clips)


class FakeYouTubeUploader:
    async def upload(
        self,
        video_path: Path,
        plan: ShortPlan,
        thumbnail_path: Path | None = None,
    ) -> str:
        assert video_path.read_bytes() == b"rendered"
        assert thumbnail_path and thumbnail_path.read_bytes() == b"thumbnail"
        return "youtube-id"


class FakeInstagramUploader:
    async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
        assert plan.instagram_caption.startswith("@wzz.unfiltered @precious.tulip1\n\n")
        assert "Instagram caption" in plan.instagram_caption
        assert plan.instagram_caption.endswith("#Reels")
        return InstagramUploadResult("instagram-id", "https://instagram.com/reel/example")


def settings_for(tmp_path: Path) -> Settings:
    base = Settings.from_env(env_file=None)
    return replace(
        base,
        groq_api_key="key",
        rights_acknowledged=True,
        upload_youtube=True,
        upload_instagram=True,
        upload_facebook=False,
        delete_uploaded_clips=False,
        shorts_selection_mode="ai_highlights",
        subtitles_enabled=False,
        youtube_channel_id="UC123",
        instagram_user_id="1789",
        instagram_access_token="token",
        instagram_hashtags_file=tmp_path / "instagram_hashtags.txt",
        instagram_caption_rotation_file=tmp_path / "instagram_captions.txt",
        work_dir=tmp_path / "work",
        database_path=tmp_path / "work" / "jobs.db",
        youtube_token_file=tmp_path / "token.json",
    )


async def test_pipeline_completes_and_uploads_to_both_platforms(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = JobRepository(settings.database_path)
    job = repository.create(1, 2, "https://youtu.be/example")
    statuses: list[JobStatus] = []
    messages: list[str] = []
    downloaded: list[str] = []

    async def notify(updated, message: str) -> None:  # noqa: ANN001
        statuses.append(updated.status)
        messages.append(message)

    async def on_download(updated, source: SourceVideo) -> None:  # noqa: ANN001
        downloaded.append(updated.source_url)

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
    )
    pipeline = WorkflowPipeline(settings, repository, services, notify, on_download)

    result = await pipeline.process(job.id)

    assert result.status == JobStatus.COMPLETE
    assert result.youtube_video_id == "youtube-id"
    assert result.instagram_media_id == "instagram-id"
    assert result.instagram_url == "https://instagram.com/reel/example"
    assert result.short_title == "Short title #Shorts"
    assert downloaded == ["https://youtu.be/example"]
    assert any("youtube.com/shorts/youtube-id" in message for message in messages)
    assert any("instagram.com/reel/example" in message for message in messages)
    assert statuses == [
        JobStatus.DOWNLOADING,
        JobStatus.ANALYZING,
        JobStatus.RENDERING,
        JobStatus.UPLOADING,
        JobStatus.UPLOADING,
        JobStatus.UPLOADING,
        JobStatus.UPLOADING,
        JobStatus.COMPLETE,
    ]


async def test_pipeline_renders_and_uploads_multiple_clips(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")

    class MultiPlanner:
        async def create_plans(
            self, audio_path: Path, source: SourceVideo, max_clips: int
        ) -> list[ShortPlan]:
            return [
                ShortPlan(0, 25, "First #Shorts", "First", "First #Reels"),
                ShortPlan(40, 25, "Second #Shorts", "Second", "Second #Reels"),
            ]

        async def create_full_coverage_plans(
            self, audio_path: Path, source: SourceVideo, max_clips: int
        ) -> list[ShortPlan]:
            return await self.create_plans(audio_path, source, max_clips)

    class MultiMedia(FakeMedia):
        def render_short(
            self,
            source: Path,
            output: Path,
            start_seconds: float,
            duration_seconds: float,
        ) -> Path:
            output.write_bytes(f"{start_seconds}".encode())
            return output

    class MultiYouTube:
        async def upload(
            self,
            video_path: Path,
            plan: ShortPlan,
            thumbnail_path: Path | None = None,
        ) -> str:
            assert thumbnail_path and thumbnail_path.exists()
            return f"youtube-{plan.start_seconds:g}"

    class MultiInstagram:
        async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
            suffix = f"{plan.start_seconds:g}"
            return InstagramUploadResult(
                f"instagram-{suffix}", f"https://instagram.com/reel/{suffix}"
            )

    class MultiEnhancer:
        async def enhance(self, video_path: Path, output_path: Path, public_id: str) -> Path:
            assert video_path.exists()
            output_path.write_bytes(b"enhanced")
            return output_path

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=MultiMedia(),  # type: ignore[arg-type]
        planner=MultiPlanner(),  # type: ignore[arg-type]
        enhancer=MultiEnhancer(),  # type: ignore[arg-type]
        youtube_uploader=MultiYouTube(),  # type: ignore[arg-type]
        instagram_uploader=MultiInstagram(),  # type: ignore[arg-type]
    )
    result = await WorkflowPipeline(settings, repository, services).process(job.id)
    clips = repository.list_clips(job.id)

    assert result.status == JobStatus.COMPLETE
    assert len(clips) == 2
    assert clips[0].youtube_video_id == "youtube-0"
    assert clips[0].enhancement_complete is True
    assert clips[0].output_path and clips[0].output_path.endswith("-enhanced.mp4")
    assert clips[1].youtube_video_id == "youtube-40"
    assert clips[1].instagram_media_id == "instagram-40"


async def test_one_reel_failure_does_not_skip_later_reels(tmp_path: Path) -> None:
    hashtag_file = tmp_path / "instagram_hashtags.txt"
    requested_tags = [f"#requested{index}" for index in range(36)]
    hashtag_file.write_text("\n".join(requested_tags), encoding="utf-8")
    caption_file = tmp_path / "instagram_captions.txt"
    caption_file.write_text("Caption A #special\nCaption B #other\n", encoding="utf-8")
    settings = replace(
        settings_for(tmp_path),
        upload_facebook=True,
        archive_on_upload_limit=False,
        instagram_hashtags_file=hashtag_file,
        instagram_caption_rotation_file=caption_file,
    )
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")
    instagram_attempts: list[float] = []
    facebook_attempts: list[float] = []
    instagram_captions: list[str] = []
    messages: list[str] = []

    class MultiPlanner:
        async def create_plans(
            self, audio_path: Path, source: SourceVideo, max_clips: int
        ) -> list[ShortPlan]:
            return [
                ShortPlan(0, 25, "First #Shorts", "First", "First #oldtag"),
                ShortPlan(40, 25, "Second #Shorts", "Second", "Second #oldtag"),
            ]

    class MultiMedia(FakeMedia):
        def render_short(
            self,
            source: Path,
            output: Path,
            start_seconds: float,
            duration_seconds: float,
        ) -> Path:
            output.write_bytes(f"{start_seconds}".encode())
            return output

    class MultiYouTube:
        async def upload(
            self,
            video_path: Path,
            plan: ShortPlan,
            thumbnail_path: Path | None = None,
        ) -> str:
            return f"youtube-{plan.start_seconds:g}"

    class FlakyInstagram:
        async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
            instagram_attempts.append(plan.start_seconds)
            instagram_captions.append(plan.instagram_caption)
            if plan.start_seconds == 0:
                raise UploadError("temporary Instagram upload failure")
            return InstagramUploadResult("instagram-40", "https://instagram.com/reel/40")

    class FlakyFacebook:
        async def upload(self, video_path: Path, plan: ShortPlan) -> tuple[str, str]:
            facebook_attempts.append(plan.start_seconds)
            if plan.start_seconds == 0:
                raise UploadError("temporary Facebook upload failure")
            return "facebook-40", "https://facebook.com/reel/40"

    async def notify(updated, message: str) -> None:  # noqa: ANN001
        messages.append(message)

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=MultiMedia(),  # type: ignore[arg-type]
        planner=MultiPlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=MultiYouTube(),  # type: ignore[arg-type]
        instagram_uploader=FlakyInstagram(),  # type: ignore[arg-type]
        facebook_uploader=FlakyFacebook(),  # type: ignore[arg-type]
    )
    result = await WorkflowPipeline(settings, repository, services, notify).process(job.id)
    clips = repository.list_clips(job.id)

    assert result.status == JobStatus.COMPLETE
    assert instagram_attempts == [0, 40]
    assert facebook_attempts == [0, 40]
    assert all(caption.count("#") == 30 for caption in instagram_captions)
    assert all(
        caption.startswith("@wzz.unfiltered @precious.tulip1\n\n") for caption in instagram_captions
    )
    assert "Caption A #special" in instagram_captions[0]
    assert "Caption B #other" in instagram_captions[1]
    assert all("#oldtag" not in caption for caption in instagram_captions)
    assert clips[0].instagram_media_id is None
    assert clips[0].facebook_video_id is None
    assert clips[1].instagram_media_id == "instagram-40"
    assert clips[1].facebook_video_id == "facebook-40"
    assert "Facebook and Instagram uploads pending" in result.progress_message
    assert services.unavailable_platforms == {}
    assert any("continue with the next Reel" in message for message in messages)


async def test_full_coverage_uploads_each_clip_before_generating_the_next(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        shorts_selection_mode="full_coverage",
        max_shorts_per_video=0,
        groq_metadata_delay_seconds=0,
    )
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")
    events: list[str] = []

    class StreamingPlanner:
        async def transcribe(self, audio_path: Path) -> str:
            return "[0.00-90.00] Full transcript"

        async def enrich_plan(
            self,
            plan: ShortPlan,
            source: SourceVideo,
            full_transcript: str,
            hashtag_offset: int = 0,
        ) -> ShortPlan:
            return ShortPlan(
                plan.start_seconds,
                plan.duration_seconds,
                f"Part {plan.start_seconds:g} #Shorts",
                "Detailed description",
                "Detailed caption #Reels",
            )

    class StreamingMedia(FakeMedia):
        def render_short(
            self,
            source: Path,
            output: Path,
            start_seconds: float,
            duration_seconds: float,
        ) -> Path:
            output.write_bytes(b"rendered")
            return output

    class StreamingYouTube:
        async def upload(
            self,
            video_path: Path,
            plan: ShortPlan,
            thumbnail_path: Path | None = None,
        ) -> str:
            return f"youtube-{plan.start_seconds:g}"

    class StreamingInstagram:
        async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
            suffix = f"{plan.start_seconds:g}"
            return InstagramUploadResult(
                f"instagram-{suffix}",
                f"https://instagram.com/reel/{suffix}",
            )

    async def notify(updated, message: str) -> None:  # noqa: ANN001
        events.append(message)

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=StreamingMedia(),  # type: ignore[arg-type]
        planner=StreamingPlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=StreamingYouTube(),  # type: ignore[arg-type]
        instagram_uploader=StreamingInstagram(),  # type: ignore[arg-type]
    )
    result = await WorkflowPipeline(settings, repository, services, notify).process(job.id)

    assert result.status == JobStatus.COMPLETE
    assert len(repository.list_clips(job.id)) == 3
    metadata_2 = events.index("Generating detailed metadata for Short 2/3")
    instagram_1 = events.index("Publishing Reel 1/3 to Instagram")
    assert instagram_1 < metadata_2


async def test_upload_limits_create_open_folder_and_do_not_fail_job(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        archive_on_upload_limit=True,
        archive_dir=tmp_path / "pending_uploads",
        open_upload_limit_folder=False,
    )
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")
    messages: list[str] = []

    async def notify(updated, message: str) -> None:  # noqa: ANN001
        messages.append(message)

    class LimitedYouTube:
        async def upload(
            self,
            video_path: Path,
            plan: ShortPlan,
            thumbnail_path: Path | None = None,
        ) -> str:
            raise UploadLimitError("YouTube", "daily limit")

    class LimitedInstagram:
        async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
            raise UploadLimitError("Instagram", "publishing limit")

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=LimitedYouTube(),  # type: ignore[arg-type]
        instagram_uploader=LimitedInstagram(),  # type: ignore[arg-type]
    )
    result = await WorkflowPipeline(settings, repository, services, notify).process(job.id)

    assert result.status == JobStatus.COMPLETE
    assert "YouTube limit reached" in messages
    assert result.archive_path is not None
    folder_path = Path(result.archive_path)
    assert folder_path.is_dir()
    assert (folder_path / "metadata.json").exists()
    assert (folder_path / "upload-manifest.csv").exists()
    assert list((folder_path / "videos").glob("*.mp4"))


async def test_expired_platform_token_does_not_stop_local_generation(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        archive_on_upload_limit=True,
        archive_dir=tmp_path / "pending_uploads",
        open_upload_limit_folder=False,
    )
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")

    class ExpiredInstagram:
        async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
            raise UploadError("Instagram token expired")

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=ExpiredInstagram(),  # type: ignore[arg-type]
    )

    result = await WorkflowPipeline(settings, repository, services).process(job.id)

    assert result.status == JobStatus.COMPLETE
    assert "Instagram uploads pending" in result.progress_message
    assert result.archive_path and Path(result.archive_path).is_dir()
    clip = repository.list_clips(job.id)[0]
    assert clip.youtube_video_id == "youtube-id"
    assert clip.instagram_media_id is None


async def test_pipeline_can_resume_an_already_downloaded_job(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")
    repository.update(job.id, source_title="Previously downloaded")
    job_dir = settings.work_dir / "jobs" / job.id
    job_dir.mkdir(parents=True)
    (job_dir / "source.mkv").write_bytes(b"existing source")
    statuses: list[JobStatus] = []

    async def notify(updated, message: str) -> None:  # noqa: ANN001
        statuses.append(updated.status)

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
    )
    pipeline = WorkflowPipeline(settings, repository, services, notify)

    result = await pipeline.process(job.id, reuse_downloaded=True)

    assert result.status == JobStatus.COMPLETE
    assert JobStatus.DOWNLOADING not in statuses
    assert statuses[0] == JobStatus.ANALYZING


async def test_pipeline_publishes_each_clip_to_facebook(tmp_path: Path) -> None:
    settings = replace(settings_for(tmp_path), upload_facebook=True)
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")

    class FakeFacebook:
        async def upload(self, video_path: Path, plan: ShortPlan) -> tuple[str, str]:
            assert video_path.exists()
            return "facebook-id", "https://www.facebook.com/reel/facebook-id"

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
        facebook_uploader=FakeFacebook(),  # type: ignore[arg-type]
    )

    result = await WorkflowPipeline(settings, repository, services).process(job.id)
    clip = repository.list_clips(job.id)[0]

    assert result.facebook_video_id == "facebook-id"
    assert result.facebook_url == "https://www.facebook.com/reel/facebook-id"
    assert clip.facebook_video_id == "facebook-id"
    assert clip.facebook_url == "https://www.facebook.com/reel/facebook-id"


async def test_deletes_clip_files_after_every_platform_upload(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        upload_facebook=True,
        delete_uploaded_clips=True,
    )
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")

    class FakeFacebook:
        async def upload(self, video_path: Path, plan: ShortPlan) -> tuple[str, str]:
            return "facebook-id", "https://www.facebook.com/reel/facebook-id"

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
        facebook_uploader=FakeFacebook(),  # type: ignore[arg-type]
    )

    result = await WorkflowPipeline(settings, repository, services).process(job.id)
    clip = repository.list_clips(job.id)[0]
    job_dir = settings.work_dir / "jobs" / job.id

    assert result.status == JobStatus.COMPLETE
    assert clip.youtube_video_id == "youtube-id"
    assert clip.facebook_video_id == "facebook-id"
    assert clip.output_path is None
    assert clip.thumbnail_path is None
    assert not list(job_dir.glob("short-*.mp4"))
    assert not list(job_dir.glob("thumbnail-*.jpg"))
    assert "deleted 1 fully published clip file(s)" in result.progress_message


async def test_keeps_clip_files_while_any_platform_upload_is_pending(tmp_path: Path) -> None:
    settings = replace(
        settings_for(tmp_path),
        upload_facebook=True,
        delete_uploaded_clips=True,
        archive_on_upload_limit=False,
    )
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")

    class FailingFacebook:
        async def upload(self, video_path: Path, plan: ShortPlan) -> tuple[str, str]:
            raise UploadError("temporary Facebook failure")

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
        facebook_uploader=FailingFacebook(),  # type: ignore[arg-type]
    )

    result = await WorkflowPipeline(settings, repository, services).process(job.id)
    clip = repository.list_clips(job.id)[0]

    assert result.status == JobStatus.COMPLETE
    assert clip.facebook_video_id is None
    assert clip.output_path is not None
    assert Path(clip.output_path).exists()


async def test_skips_reprocessing_clips_already_published_everywhere(tmp_path: Path) -> None:
    settings = replace(settings_for(tmp_path), delete_uploaded_clips=True)
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
    )
    pipeline = WorkflowPipeline(settings, repository, services)

    first_run = await pipeline.process(job.id)
    assert first_run.status == JobStatus.COMPLETE
    clip = repository.list_clips(job.id)[0]
    assert clip.output_path is None  # deleted after publishing everywhere

    # Reprocessing the job must not re-render or re-upload the published clip.
    second_run = await pipeline.process(job.id, reuse_downloaded=True)
    clip = repository.list_clips(job.id)[0]

    assert second_run.status == JobStatus.COMPLETE
    assert clip.output_path is None
    assert clip.youtube_video_id == "youtube-id"


async def test_facebook_upload_limit_sets_cooldown_and_pauses_facebook(
    tmp_path: Path,
) -> None:
    settings = replace(
        settings_for(tmp_path),
        upload_facebook=True,
        facebook_limit_cooldown_hours=24.0,
        archive_on_upload_limit=False,
    )
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")
    messages: list[str] = []

    class MultiPlanner:
        async def create_plans(
            self, audio_path: Path, source: SourceVideo, max_clips: int
        ) -> list[ShortPlan]:
            return [
                ShortPlan(0, 25, "First #Shorts", "First", "Instagram caption First"),
                ShortPlan(40, 25, "Second #Shorts", "Second", "Instagram caption Second"),
            ]

    class MultiMedia(FakeMedia):
        def render_short(
            self,
            source: Path,
            output: Path,
            start_seconds: float,
            duration_seconds: float,
        ) -> Path:
            output.write_bytes(b"rendered")
            return output

    class LimitedFacebook:
        async def upload(self, video_path: Path, plan: ShortPlan) -> tuple[str, str]:
            raise UploadLimitError(
                "Facebook",
                "We limit how often you can post, comment or do other things in a "
                "given amount of time in order to help protect the community from spam.",
            )

    async def notify(updated, message: str) -> None:  # noqa: ANN001
        messages.append(message)

    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=MultiMedia(),  # type: ignore[arg-type]
        planner=MultiPlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
        facebook_uploader=LimitedFacebook(),  # type: ignore[arg-type]
    )
    result = await WorkflowPipeline(settings, repository, services, notify).process(job.id)
    clips = repository.list_clips(job.id)

    assert result.status == JobStatus.COMPLETE
    assert all(clip.facebook_video_id is None for clip in clips)
    # Facebook was attempted once, then paused for the cooldown window.
    assert "Facebook" in services.platform_cooldowns
    assert services.platform_unavailable("Facebook") is not None
    assert any("pausing Facebook for 24h" in message for message in messages)


class SubtitleFakeMedia(FakeMedia):
    def __init__(self) -> None:
        self.burn_calls = 0

    def burn_subtitles(
        self,
        video: Path,
        ass_path: Path,
        output: Path,
        fonts_dir: Path | None = None,
    ) -> Path:
        self.burn_calls += 1
        assert video.read_bytes() == b"rendered"
        ass_text = Path(ass_path).read_text(encoding="utf-8")
        assert "[Script Info]" in ass_text
        assert "HELLO" in ass_text
        output.write_bytes(b"subtitled")
        return output


class SubtitleFakePlanner(FakePlanner):
    async def transcribe_words(self, audio_path: Path):  # noqa: ANN201
        return [
            WordCue("hello", 10.0, 10.4),
            WordCue("creator", 10.5, 10.9),
            WordCue("world", 11.0, 11.4),
        ]


class SubtitleAwareYouTubeUploader:
    async def upload(
        self,
        video_path: Path,
        plan: ShortPlan,
        thumbnail_path: Path | None = None,
    ) -> str:
        assert video_path.read_bytes() == b"subtitled"
        return "youtube-id"


async def test_pipeline_burns_word_synced_subtitles(tmp_path: Path) -> None:
    settings = replace(settings_for(tmp_path), subtitles_enabled=True)
    repository = JobRepository(settings.database_path)
    job = repository.create(0, 0, "https://youtu.be/example")

    media = SubtitleFakeMedia()
    services = WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=media,  # type: ignore[arg-type]
        planner=SubtitleFakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=SubtitleAwareYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=FakeInstagramUploader(),  # type: ignore[arg-type]
    )
    pipeline = WorkflowPipeline(settings, repository, services)

    result = await pipeline.process(job.id)
    clip = repository.list_clips(job.id)[0]
    job_dir = settings.work_dir / "jobs" / job.id

    assert result.status == JobStatus.COMPLETE
    assert media.burn_calls == 1
    assert clip.output_path is not None
    assert clip.output_path.endswith("-subtitled.mp4")
    assert Path(clip.output_path).read_bytes() == b"subtitled"
    assert (job_dir / "transcript-words.json").exists()

    # A resume must reuse the existing subtitled file instead of burning again.
    second = await pipeline.process(job.id, reuse_downloaded=True)
    assert second.status == JobStatus.COMPLETE
    assert media.burn_calls == 1
