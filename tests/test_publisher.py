from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from test_pipeline import FakeDownloader, FakeMedia, FakePlanner, FakeYouTubeUploader, settings_for

from shorts_bot.db import JobRepository
from shorts_bot.models import ChannelPlatform, JobStatus
from shorts_bot.pipeline import WorkflowPipeline, WorkflowServices
from shorts_bot.publisher import (
    platform_scheduling_enabled,
    publish_platform,
    run_due_publishes,
)


def deferred_settings(tmp_path: Path):
    return replace(
        settings_for(tmp_path),
        upload_instagram=False,
        upload_facebook=False,
        youtube_schedule_times="00:00",
        schedule_timezone="UTC",
        archive_on_upload_limit=False,
        open_upload_limit_folder=False,
    )


def services_with_youtube() -> WorkflowServices:
    return WorkflowServices(
        downloader=FakeDownloader(),  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        planner=FakePlanner(),  # type: ignore[arg-type]
        enhancer=None,
        youtube_uploader=FakeYouTubeUploader(),  # type: ignore[arg-type]
        instagram_uploader=None,
    )


async def render_pending_job(settings, repository, url: str) -> str:
    """Run the pipeline with uploads deferred; returns the job id."""
    job = repository.create(0, 0, url)
    result = await WorkflowPipeline(
        settings, repository, services_with_youtube()
    ).process(job.id)
    assert result.status == JobStatus.COMPLETE
    clip = repository.list_clips(job.id)[0]
    assert clip.output_path is not None and Path(clip.output_path).exists()
    assert clip.youtube_video_id is None
    return job.id


async def test_pipeline_defers_youtube_upload_when_scheduled(tmp_path: Path) -> None:
    settings = deferred_settings(tmp_path)
    repository = JobRepository(settings.database_path)
    job_id = await render_pending_job(settings, repository, "https://youtu.be/defer")
    result = repository.get(job_id)
    assert result is not None
    assert "YouTube uploads pending" in (result.progress_message or "")


async def test_next_pending_clip_is_fifo_and_platform_specific(tmp_path: Path) -> None:
    settings = deferred_settings(tmp_path)
    repository = JobRepository(settings.database_path)
    first = await render_pending_job(settings, repository, "https://youtu.be/first")
    second = await render_pending_job(settings, repository, "https://youtu.be/second")

    pending = repository.next_pending_clip(ChannelPlatform.YOUTUBE)
    assert pending is not None and pending.job_id == first

    repository.update_clip(
        first, 1, youtube_video_id="done", youtube_uploaded_at="2026-09-25T00:00:01+00:00"
    )
    pending = repository.next_pending_clip(ChannelPlatform.YOUTUBE)
    assert pending is not None and pending.job_id == second

    # The Instagram column was never filled, so Instagram still sees the clip.
    instagram_pending = repository.next_pending_clip(ChannelPlatform.INSTAGRAM)
    assert instagram_pending is not None and instagram_pending.job_id == first


async def test_publish_platform_uploads_oldest_clip(tmp_path: Path) -> None:
    settings = deferred_settings(tmp_path)
    repository = JobRepository(settings.database_path)
    job_id = await render_pending_job(settings, repository, "https://youtu.be/pub")

    published = await publish_platform(
        settings,
        repository,
        services_with_youtube(),
        ChannelPlatform.YOUTUBE,
        max_uploads=1,
    )
    assert len(published) == 1
    clip = repository.list_clips(job_id)[0]
    assert clip.youtube_video_id == "youtube-id"

    count = repository.count_platform_uploads_since(
        ChannelPlatform.YOUTUBE, "2000-01-01T00:00:00+00:00"
    )
    assert count == 1


async def test_publish_platform_no_pending(tmp_path: Path) -> None:
    settings = deferred_settings(tmp_path)
    repository = JobRepository(settings.database_path)
    published = await publish_platform(
        settings,
        repository,
        services_with_youtube(),
        ChannelPlatform.YOUTUBE,
        max_uploads=1,
    )
    assert published == []


async def test_publish_platform_disabled_without_schedule(tmp_path: Path) -> None:
    settings = replace(deferred_settings(tmp_path), youtube_schedule_times="")
    repository = JobRepository(settings.database_path)
    published = await publish_platform(
        settings,
        repository,
        services_with_youtube(),
        ChannelPlatform.YOUTUBE,
    )
    assert published == []
    assert platform_scheduling_enabled(settings, ChannelPlatform.YOUTUBE) is False
    assert platform_scheduling_enabled(settings, ChannelPlatform.INSTAGRAM) is False


async def test_run_due_publishes_uses_daily_credits(tmp_path: Path) -> None:
    settings = deferred_settings(tmp_path)
    repository = JobRepository(settings.database_path)
    first = await render_pending_job(settings, repository, "https://youtu.be/c1")
    await render_pending_job(settings, repository, "https://youtu.be/c2")

    # One slot ("00:00" UTC) has passed today, so exactly one upload is owed.
    published = await run_due_publishes(settings, repository, services_with_youtube())
    assert len(published) == 1
    assert published[0].job_id == first

    # Second run: the credit is already consumed by the DB timestamp, so no more.
    published_again = await run_due_publishes(settings, repository, services_with_youtube())
    assert published_again == []
