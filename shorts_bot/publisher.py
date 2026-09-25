"""Scheduled per-platform publishing with catch-up credits.

HotClip exports finish in the watched export directory and land in the
``publication_clips`` SQLite queue. This module publishes that queue at each
platform's configured times:

* Every passed slot owes ``*_UPLOADS_PER_SLOT`` uploads for that platform.
* Upload timestamps in SQLite track today's consumption, so a missed or
  empty slot keeps its credit. The next ready clip publishes as soon as a
  credit exists (catch-up), then the normal schedule resumes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC
from pathlib import Path

from .config import Settings
from .db import JobRepository
from .errors import UploadError, UploadLimitError, WorkflowError
from .facebook import FacebookReelUploader
from .hashtags import plan_with_hashtags
from .instagram import InstagramUploader
from .media import MediaProcessor
from .models import ChannelPlatform, Publication
from .scheduler import (
    PlatformSchedule,
    due_credits,
    now_in,
    platform_schedules,
    schedule_timezone,
)
from .youtube import YouTubeUploader

logger = logging.getLogger(__name__)

Reporter = Callable[[str], None]


def _settings_schedules(settings: Settings) -> dict[ChannelPlatform, PlatformSchedule]:
    return platform_schedules(
        (settings.youtube_schedule_times, settings.youtube_uploads_per_slot),
        (settings.instagram_schedule_times, settings.instagram_uploads_per_slot),
        (settings.facebook_schedule_times, settings.facebook_uploads_per_slot),
    )


def platform_scheduling_enabled(settings: Settings, platform: ChannelPlatform) -> bool:
    spec, _ = settings.schedule_spec(platform.value)
    return bool(spec)


class Publisher:
    """Uploads queued HotClip exports to YouTube, Instagram, and Facebook."""

    def __init__(
        self,
        settings: Settings,
        repository: JobRepository,
        media: MediaProcessor | None = None,
        youtube: YouTubeUploader | None = None,
        instagram: InstagramUploader | None = None,
        facebook: FacebookReelUploader | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.media = media or MediaProcessor()
        self.youtube = (
            youtube
            if youtube is not None
            else (
                YouTubeUploader(
                    settings.youtube_token_file,
                    settings.youtube_privacy_status,
                    settings.youtube_channel_id,
                )
                if settings.upload_youtube
                else None
            )
        )
        self.instagram = (
            instagram
            if instagram is not None
            else (
                InstagramUploader(
                    user_id=settings.instagram_user_id,
                    access_token=settings.instagram_access_token,
                    api_version=settings.instagram_graph_api_version,
                )
                if settings.upload_instagram
                else None
            )
        )
        self.facebook = (
            facebook
            if facebook is not None
            else (
                FacebookReelUploader(
                    page_id=settings.facebook_page_id,
                    access_token=settings.facebook_access_token,
                    api_version=settings.facebook_graph_api_version,
                )
                if settings.upload_facebook
                else None
            )
        )
        # monotonic deadlines: a Meta spam-protection block pauses Facebook
        # uploads for the configured cooldown instead of being re-probed.
        self._facebook_cooldown_until = 0.0

    def _uploader_for(self, platform: ChannelPlatform):  # noqa: ANN202
        if platform is ChannelPlatform.YOUTUBE:
            return self.youtube
        if platform is ChannelPlatform.INSTAGRAM:
            return self.instagram
        return self.facebook

    async def upload_one(self, publication: Publication, platform: ChannelPlatform) -> Publication:
        uploader = self._uploader_for(platform)
        if uploader is None:
            raise WorkflowError(f"{platform.value} uploading is not enabled.")
        mp4_path = Path(publication.mp4_path)
        if not mp4_path.exists():
            raise WorkflowError(
                f"Clip file is missing: {mp4_path}. It was moved or deleted after queueing."
            )
        duration = self.media.probe_duration(mp4_path)
        plan = plan_with_hashtags(publication.to_plan(duration), platform, self.settings)

        if platform is ChannelPlatform.YOUTUBE:
            thumbnail = Path(publication.cover_path) if publication.cover_path else None
            video_id = await uploader.upload(mp4_path, plan, thumbnail)
            return self.repository.update_publication(
                publication.id,
                youtube_video_id=video_id,
                youtube_uploaded_at=_utc_now_iso(),
                error=None,
            )
        if platform is ChannelPlatform.INSTAGRAM:
            result = await uploader.upload(mp4_path, plan)
            return self.repository.update_publication(
                publication.id,
                instagram_media_id=result.media_id,
                instagram_url=result.permalink,
                instagram_uploaded_at=_utc_now_iso(),
                error=None,
            )
        video_id, url = await uploader.upload(mp4_path, plan)
        return self.repository.update_publication(
            publication.id,
            facebook_video_id=video_id,
            facebook_url=url,
            facebook_uploaded_at=_utc_now_iso(),
            error=None,
        )

    async def publish_platform(
        self,
        platform: ChannelPlatform,
        max_uploads: int = 1,
        report: Reporter | None = None,
    ) -> list[Publication]:
        def _report(message: str) -> None:
            logger.info("%s", message)
            if report:
                report(message)

        if self._uploader_for(platform) is None:
            _report(f"{platform.value} uploading is disabled; nothing to publish.")
            return []
        if (
            platform is ChannelPlatform.FACEBOOK
            and time.monotonic() < self._facebook_cooldown_until
        ):
            remaining = max(
                0.0,
                (self._facebook_cooldown_until - time.monotonic()) / 3600,
            )
            _report(
                f"Facebook is paused for {remaining:.1f}h after its upload limit; "
                "it will retry automatically."
            )
            return []

        published: list[Publication] = []
        for _ in range(max(1, max_uploads)):
            publication = self.repository.next_pending_publication(platform)
            if publication is None:
                if not published:
                    _report(f"No queued clips waiting for {platform.value}.")
                break
            if not Path(publication.mp4_path).exists():
                logger.warning(
                    "Queued clip file vanished, skipping until it returns: %s",
                    publication.mp4_path,
                )
                self.repository.update_publication(
                    publication.id,
                    error="clip file missing on disk",
                )
                break
            _report(
                f"Publishing to {platform.value}: {publication.title} "
                f"({Path(publication.mp4_path).name})"
            )
            try:
                updated = await self.upload_one(publication, platform)
            except UploadLimitError as exc:
                if platform is ChannelPlatform.FACEBOOK:
                    hours = self.settings.facebook_limit_cooldown_hours
                    self._facebook_cooldown_until = time.monotonic() + hours * 3600
                    _report(
                        f"Facebook upload limit reached; pausing Facebook for {hours:g}h "
                        f"and keeping its credits: {exc}"
                    )
                else:
                    _report(
                        f"{platform.value} upload limit reached; remaining credits will "
                        f"catch up on the next run: {exc}"
                    )
                break
            except (UploadError, WorkflowError) as exc:
                self.repository.update_publication(publication.id, error=str(exc))
                _report(f"{platform.value} upload failed; the clip stays queued: {exc}")
                break
            published.append(updated)
            self._cleanup_if_done(updated)
        return published

    def _cleanup_if_done(self, publication: Publication) -> None:
        if not self.settings.delete_uploaded_clips:
            return
        active = [
            platform
            for platform in ChannelPlatform
            if self._uploader_for(platform) is not None
        ]
        if not publication.published_everywhere(active):
            return
        try:
            Path(publication.mp4_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete published clip %s", publication.mp4_path)

    async def publish_due(
        self,
        platform: ChannelPlatform,
        report: Reporter | None = None,
    ) -> list[Publication]:
        """Publish exactly the uploads one platform is owed by its schedule now."""

        def _report(message: str) -> None:
            logger.info("%s", message)
            if report:
                report(message)

        schedules = _settings_schedules(self.settings)
        schedule = schedules.get(platform)
        if schedule is None:
            _report(f"{platform.value} has no schedule configured; nothing to publish.")
            return []
        timezone = schedule_timezone(self.settings.schedule_timezone)
        local_now = now_in(timezone)
        start_of_today_utc = (
            local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
            .isoformat(timespec="seconds")
        )
        uploads_done = self.repository.count_platform_uploads_since(
            platform, start_of_today_utc
        )
        credits = due_credits(schedule, uploads_done, local_now)
        if credits <= 0:
            owed_today = schedule.uploads_owed_until(
                local_now.weekday(), local_now.time().replace(tzinfo=None)
            )
            _report(
                f"No {platform.value} uploads due right now "
                f"(today: {uploads_done} done, {owed_today} owed)."
            )
            return []
        _report(
            f"{platform.value}: {credits} upload credit(s) due "
            f"({uploads_done} already done today)."
        )
        return await self.publish_platform(platform, max_uploads=credits, report=report)

    async def publish_all_due(self, report: Reporter | None = None) -> list[Publication]:
        published: list[Publication] = []
        for platform in _settings_schedules(self.settings):
            published.extend(await self.publish_due(platform, report=report))
        return published


def _utc_now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
