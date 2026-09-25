"""Scheduled per-platform publishing with catch-up credits.

The pipeline renders clips and leaves uploads pending whenever a platform
has schedule times configured. This module consumes the rendered queue:

* Every passed slot grants one upload credit for that platform (per day).
* Each clip already uploaded to a platform today consumes one credit.
* If a slot had nothing to upload, its credit stays — the next ready clip
  is published as soon as it exists (catch-up), then the normal schedule
  resumes. Upload timestamps live in SQLite, so credits are correct even
  across separate scheduled runs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC

from .config import Settings
from .db import JobRepository
from .errors import WorkflowError
from .models import ChannelPlatform, JobClip
from .pipeline import WorkflowPipeline, WorkflowServices
from .scheduler import (
    PlatformSchedule,
    due_credits,
    now_in,
    platform_schedules,
    schedule_timezone,
)

logger = logging.getLogger(__name__)


def _settings_schedules(settings: Settings) -> dict[ChannelPlatform, PlatformSchedule]:
    return platform_schedules(
        settings.youtube_schedule_times,
        settings.instagram_schedule_times,
        settings.facebook_schedule_times,
    )


def platform_scheduling_enabled(settings: Settings, platform: ChannelPlatform) -> bool:
    if platform is ChannelPlatform.YOUTUBE:
        return settings.upload_youtube and bool(settings.youtube_schedule_times)
    if platform is ChannelPlatform.INSTAGRAM:
        return settings.upload_instagram and bool(settings.instagram_schedule_times)
    return settings.upload_facebook and bool(settings.facebook_schedule_times)


async def publish_platform(
    settings: Settings,
    repository: JobRepository,
    services: WorkflowServices,
    platform: ChannelPlatform,
    max_uploads: int = 1,
    on_status: Callable[[str], None] | None = None,
) -> list[JobClip]:
    """Upload up to ``max_uploads`` pending clips for one platform, oldest first."""

    def report(message: str) -> None:
        logger.info("%s", message)
        if on_status:
            on_status(message)

    if not platform_scheduling_enabled(settings, platform):
        report(f"{platform.value} scheduling is not enabled; nothing to publish.")
        return []

    reason = services.platform_unavailable(platform.value)
    if reason is not None:
        report(f"{platform.value} is cooling down: {reason}")
        return []

    pipeline = WorkflowPipeline(settings, repository, services)
    published: list[JobClip] = []
    for _ in range(max(1, max_uploads)):
        clip = repository.next_pending_clip(platform)
        if clip is None:
            if not published:
                report(f"No rendered clips waiting for {platform.value}.")
            break
        job = repository.get(clip.job_id)
        if job is None:
            logger.warning("Skipping clip with unknown job %s", clip.job_id)
            continue
        report(
            f"Publishing {platform.value} clip {clip.clip_index} from job {job.id}: "
            f"{clip.title}"
        )
        try:
            updated = await pipeline.publish_clip(job, clip, platform)
        except WorkflowError as exc:
            report(f"{platform.value} publish was skipped: {exc}")
            break
        done = (
            updated.instagram_media_id
            if platform is ChannelPlatform.INSTAGRAM
            else updated.youtube_video_id
            if platform is ChannelPlatform.YOUTUBE
            else updated.facebook_video_id
        )
        if done:
            published.append(updated)
            if settings.delete_uploaded_clips and pipeline._clip_published_everywhere(updated):
                pipeline._delete_published_clip_files(job, [updated])
        else:
            # Upload failed or the platform hit its limit; try again next slot.
            break
    return published


async def publish_platform_due(
    settings: Settings,
    repository: JobRepository,
    services: WorkflowServices,
    platform: ChannelPlatform,
    on_status: Callable[[str], None] | None = None,
) -> list[JobClip]:
    """Publish exactly the uploads one platform is owed by its schedule right now."""

    def report(message: str) -> None:
        logger.info("%s", message)
        if on_status:
            on_status(message)

    schedule = _settings_schedules(settings).get(platform)
    if schedule is None or not platform_scheduling_enabled(settings, platform):
        report(f"{platform.value} has no schedule configured; nothing to publish.")
        return []
    timezone = schedule_timezone(settings.schedule_timezone)
    local_now = now_in(timezone)
    start_of_today_utc = (
        local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
        .isoformat(timespec="seconds")
    )
    uploads_today = repository.count_platform_uploads_since(platform, start_of_today_utc)
    credits = due_credits(schedule, uploads_today, local_now)
    if credits <= 0:
        report(f"No {platform.value} upload slot is due yet (next run will catch up).")
        return []
    return await publish_platform(
        settings,
        repository,
        services,
        platform,
        max_uploads=credits,
        on_status=on_status,
    )


async def run_due_publishes(
    settings: Settings,
    repository: JobRepository,
    services: WorkflowServices,
    on_status: Callable[[str], None] | None = None,
) -> list[JobClip]:
    """Publish pending clips for every platform whose schedule has due credits today."""
    published: list[JobClip] = []
    for platform in _settings_schedules(settings):
        published.extend(
            await publish_platform_due(
                settings,
                repository,
                services,
                platform,
                on_status=on_status,
            )
        )
    return published
