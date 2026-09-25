from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path

from .ai import AIPlanner, apply_instagram_hashtags, full_coverage_plans
from .archive import build_job_folder, open_local_folder
from .config import Settings
from .db import JobRepository
from .downloader import VideoDownloader
from .enhancer import APIMarketVideoEnhancer, CloudinaryTemporaryVideoHost
from .errors import UploadError, UploadLimitError, WorkflowError
from .facebook import FacebookReelUploader
from .instagram import InstagramUploader
from .media import MediaProcessor
from .models import Job, JobClip, JobStatus, ShortPlan, SourceVideo
from .youtube import YouTubeUploader

logger = logging.getLogger(__name__)
StatusCallback = Callable[[Job, str], Awaitable[None]]
DownloadedCallback = Callable[[Job, SourceVideo], Awaitable[None]]


@dataclass(slots=True)
class WorkflowServices:
    downloader: VideoDownloader
    media: MediaProcessor
    planner: AIPlanner
    enhancer: APIMarketVideoEnhancer | None
    youtube_uploader: YouTubeUploader | None
    instagram_uploader: InstagramUploader | None
    facebook_uploader: FacebookReelUploader | None = None
    unavailable_platforms: dict[str, str] = field(default_factory=dict)
    # monotonic time until which a platform is skipped after an upload-limit
    # error, so Meta spam-protection blocks are allowed to lift instead of
    # being renewed by repeated probing.
    platform_cooldowns: dict[str, float] = field(default_factory=dict)

    def platform_unavailable(self, name: str) -> str | None:
        """Reason a platform should be skipped, or None if it may be tried."""
        now = time.monotonic()
        cooldown_until = self.platform_cooldowns.get(name, 0.0)
        if now < cooldown_until:
            return self.unavailable_platforms.get(name, f"{name} limit cooldown active")
        if name in self.platform_cooldowns:
            # Cooldown expired: allow a fresh attempt.
            self.platform_cooldowns.pop(name, None)
            self.unavailable_platforms.pop(name, None)
        return self.unavailable_platforms.get(name)

    async def preflight(self) -> list[str]:
        """Check credentials before downloads and isolate unavailable upload platforms."""
        report: list[str] = []
        self.unavailable_platforms.clear()

        model, transcription_model = await self.planner.check_models()
        report.append(f"Groq ready ({model}; {transcription_model})")

        if self.enhancer:
            await self.enhancer.check_connection()
            report.append("Cloudinary ready for API.market enhancement")

        if self.youtube_uploader:
            try:
                channel = await self.youtube_uploader.check_connection()
                report.append(f"YouTube ready ({channel})")
            except UploadError as exc:
                self.unavailable_platforms["YouTube"] = str(exc)
                report.append(f"YouTube unavailable ({exc})")

        if self.instagram_uploader:
            try:
                username = await self.instagram_uploader.check_connection()
                report.append(f"Instagram ready (@{username})")
            except UploadError as exc:
                self.unavailable_platforms["Instagram"] = str(exc)
                report.append(f"Instagram unavailable ({exc})")

        if self.facebook_uploader:
            try:
                page_name = await self.facebook_uploader.check_connection()
                report.append(f"Facebook ready ({page_name})")
            except UploadError as exc:
                self.unavailable_platforms["Facebook"] = str(exc)
                report.append(f"Facebook unavailable ({exc})")
        return report

    @classmethod
    def from_settings(cls, settings: Settings) -> WorkflowServices:
        return cls(
            downloader=VideoDownloader(
                cookies_from_browser=settings.ytdlp_cookies_from_browser,
                browser_profile=settings.ytdlp_browser_profile,
                cookie_file=settings.ytdlp_cookie_file,
            ),
            media=MediaProcessor(
                video_layout=settings.video_layout,
                allow_upscale=settings.video_allow_upscale,
                video_crf=settings.video_crf,
                video_preset=settings.video_preset,
            ),
            planner=AIPlanner(
                api_key=settings.groq_api_key,
                model=settings.groq_model,
                fallback_model=settings.groq_fallback_model,
                transcription_model=settings.groq_transcription_model,
                target_duration=settings.clip_duration_seconds,
                max_transcript_chars=settings.groq_max_transcript_chars,
                youtube_description_target_chars=settings.youtube_description_target_chars,
                instagram_caption_target_chars=settings.instagram_caption_target_chars,
                instagram_hashtags=settings.instagram_hashtags(),
                metadata_delay_seconds=settings.groq_metadata_delay_seconds,
            ),
            enhancer=(
                APIMarketVideoEnhancer(
                    api_key=settings.apimarket_api_key,
                    temporary_host=CloudinaryTemporaryVideoHost(
                        cloud_name=settings.cloudinary_cloud_name,
                        api_key=settings.cloudinary_api_key,
                        api_secret=settings.cloudinary_api_secret,
                    ),
                    base_url=settings.apimarket_base_url,
                    version=settings.apimarket_version,
                    model=settings.apimarket_model,
                    resolution=settings.apimarket_resolution,
                    timeout_seconds=settings.apimarket_timeout_seconds,
                )
                if settings.video_enhancer == "api_market"
                else None
            ),
            youtube_uploader=(
                YouTubeUploader(
                    token_file=settings.youtube_token_file,
                    privacy_status=settings.youtube_privacy_status,
                    expected_channel_id=settings.youtube_channel_id,
                )
                if settings.upload_youtube
                else None
            ),
            instagram_uploader=(
                InstagramUploader(
                    user_id=settings.instagram_user_id,
                    access_token=settings.instagram_access_token,
                    api_version=settings.instagram_graph_api_version,
                )
                if settings.upload_instagram
                else None
            ),
            facebook_uploader=(
                FacebookReelUploader(
                    page_id=settings.facebook_page_id,
                    access_token=settings.facebook_access_token,
                    api_version=settings.facebook_graph_api_version,
                )
                if settings.upload_facebook
                else None
            ),
        )


class WorkflowPipeline:
    def __init__(
        self,
        settings: Settings,
        repository: JobRepository,
        services: WorkflowServices,
        on_status: StatusCallback | None = None,
        on_downloaded: DownloadedCallback | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.services = services
        self.on_status = on_status
        self.on_downloaded = on_downloaded

    async def process(
        self,
        job_id: str,
        reuse_downloaded: bool = False,
        expand_existing: bool = False,
    ) -> Job:
        job = self.repository.get(job_id)
        if not job:
            raise KeyError(f"Unknown job {job_id}")
        job_dir = self.settings.work_dir / "jobs" / job.id

        try:
            existing_clips = self.repository.list_clips(job.id)
            if (
                reuse_downloaded
                and not expand_existing
                and not existing_clips
                and self._has_legacy_render(job)
            ):
                return await self._resume_legacy_render(job)

            if reuse_downloaded:
                source = await self._load_existing_source(job, job_dir)
            else:
                await self._status(job.id, JobStatus.DOWNLOADING, "Downloading source video")
                source = await self.services.downloader.download(job.source_url, job_dir)
                downloaded_job = self.repository.update(job.id, source_title=source.title)
                if self.on_downloaded:
                    await self.on_downloaded(downloaded_job, source)

            full_transcript: str | None = None
            audio_path = job_dir / "transcript-audio.mp3"
            if existing_clips:
                clips = existing_clips
            else:
                await self._status(
                    job.id,
                    JobStatus.ANALYZING,
                    (
                        "Transcribing once and preparing duration-based clips"
                        if self.settings.shorts_selection_mode == "full_coverage"
                        else "Transcribing with Groq and selecting multiple highlights"
                    ),
                )
                if not audio_path.exists():
                    await asyncio.to_thread(
                        self.services.media.extract_audio,
                        source.path,
                        audio_path,
                    )
                if self.settings.shorts_selection_mode == "full_coverage":
                    full_transcript = await self.services.planner.transcribe(audio_path)
                    plans = full_coverage_plans(
                        source,
                        target_duration=self.settings.clip_duration_seconds,
                        max_clips=self.settings.max_shorts_per_video,
                    )
                    clips = self.repository.save_plans(
                        job.id,
                        plans,
                        metadata_ready=False,
                    )
                else:
                    plans = await self.services.planner.create_plans(
                        audio_path,
                        source,
                        max_clips=self.settings.max_shorts_per_video,
                    )
                    clips = self.repository.save_plans(job.id, plans, metadata_ready=True)

            if any(not clip.metadata_ready for clip in clips) and full_transcript is None:
                if not audio_path.exists():
                    await asyncio.to_thread(
                        self.services.media.extract_audio,
                        source.path,
                        audio_path,
                    )
                full_transcript = await self.services.planner.transcribe(audio_path)

            uploaded_platforms = self._configured_platforms()
            blocked_platforms: dict[str, str] = {
                name: reason
                for name in ("YouTube", "Instagram", "Facebook")
                if (reason := self.services.platform_unavailable(name)) is not None
            }
            total_clips = len(clips)
            metadata_requests = 0
            for clip in clips:
                try:
                    if not clip.metadata_ready:
                        if metadata_requests and self.settings.groq_metadata_delay_seconds:
                            await asyncio.sleep(self.settings.groq_metadata_delay_seconds)
                        await self._status(
                            job.id,
                            JobStatus.ANALYZING,
                            f"Generating detailed metadata for Short "
                            f"{clip.clip_index}/{total_clips}",
                        )
                        plan = self._plan_from_clip(clip)
                        enriched = await self.services.planner.enrich_plan(
                            plan,
                            source,
                            full_transcript or "",
                            hashtag_offset=(clip.clip_index - 1) * 30,
                        )
                        clip = self.repository.update_clip(
                            job.id,
                            clip.clip_index,
                            title=enriched.title,
                            description=enriched.description,
                            instagram_caption=enriched.instagram_caption,
                            metadata_ready=1,
                            error=None,
                        )
                        metadata_requests += 1

                    clip = await self._process_clip(
                        job,
                        source,
                        clip,
                        total_clips,
                        job_dir,
                        blocked_platforms,
                    )
                except Exception as exc:
                    self.repository.update_clip(
                        job.id,
                        clip.clip_index,
                        error=_safe_error(exc),
                    )
                    raise

            clips = self.repository.list_clips(job.id)
            first = clips[0]
            archive_path: Path | None = None
            pending_platforms = self._pending_platforms(clips)
            if pending_platforms and self.settings.archive_on_upload_limit:
                await self._status(
                    job.id,
                    JobStatus.RENDERING,
                    "Creating and opening a local folder for pending platform uploads",
                )
                latest_job = self.repository.get(job.id) or job
                archive_path = await asyncio.to_thread(
                    build_job_folder,
                    latest_job,
                    clips,
                    self.settings.archive_dir,
                    pending_platforms,
                )
                if self.settings.open_upload_limit_folder:
                    await asyncio.to_thread(open_local_folder, archive_path)

            if pending_platforms:
                pending_text = " and ".join(sorted(pending_platforms))
                progress = f"Created {len(clips)} Shorts; {pending_text} uploads pending"
                if archive_path:
                    progress += f"; pending-upload folder saved at {archive_path}"
            elif uploaded_platforms:
                progress = (
                    f"Created {len(clips)} Shorts; published to {' and '.join(uploaded_platforms)}"
                )
            else:
                progress = f"Created {len(clips)} local Shorts"

            if self.settings.delete_uploaded_clips:
                deleted_clip_files = self._delete_published_clip_files(job, clips)
                if deleted_clip_files:
                    clips = self.repository.list_clips(job.id)
                    first = clips[0]
                    progress += f"; deleted {deleted_clip_files} fully published clip file(s)"

            completed = self.repository.update(
                job.id,
                status=JobStatus.COMPLETE,
                progress_message=progress,
                short_title=first.title,
                short_description=first.description,
                instagram_caption=first.instagram_caption,
                output_path=first.output_path,
                youtube_video_id=first.youtube_video_id,
                instagram_media_id=first.instagram_media_id,
                instagram_url=first.instagram_url,
                facebook_video_id=first.facebook_video_id,
                facebook_url=first.facebook_url,
                archive_path=str(archive_path) if archive_path else None,
                error=None,
            )
            await self._notify(completed, completed.progress_message)

            # Keep source and clip files whenever a platform is pending so automatic retry can
            # publish them after credentials or daily allowances recover.
            if uploaded_platforms and not self.settings.keep_work_files and not pending_platforms:
                shutil.rmtree(job_dir, ignore_errors=True)
                for clip in clips:
                    self.repository.update_clip(
                        job.id,
                        clip.clip_index,
                        output_path=None,
                        thumbnail_path=None,
                    )
                completed = self.repository.update(job.id, output_path=None)
            return completed
        except Exception as exc:
            if isinstance(exc, WorkflowError):
                logger.info("Job %s failed: %s", job.id, exc)
            else:
                logger.exception("Job %s failed unexpectedly", job.id)
            error = _safe_error(exc)
            failed = self.repository.update(
                job.id,
                status=JobStatus.FAILED,
                progress_message="Workflow failed",
                error=error,
            )
            await self._notify(failed, f"Failed: {error}")
            return failed

    def _configured_platforms(self) -> list[str]:
        platforms: list[str] = []
        if self.settings.upload_youtube:
            platforms.append("YouTube")
        if self.settings.upload_instagram:
            platforms.append("Instagram")
        if self.settings.upload_facebook:
            platforms.append("Facebook")
        return platforms

    def _pending_platforms(self, clips: list[JobClip]) -> set[str]:
        pending: set[str] = set()
        if self.settings.upload_youtube and any(not clip.youtube_video_id for clip in clips):
            pending.add("YouTube")
        if self.settings.upload_instagram and any(not clip.instagram_media_id for clip in clips):
            pending.add("Instagram")
        if self.settings.upload_facebook and any(not clip.facebook_video_id for clip in clips):
            pending.add("Facebook")
        return pending

    def _clip_published_everywhere(self, clip: JobClip) -> bool:
        """True when every active upload platform already has this clip."""
        checks: list[bool] = []
        if self.services.youtube_uploader:
            checks.append(bool(clip.youtube_video_id))
        if self.services.instagram_uploader:
            checks.append(bool(clip.instagram_media_id))
        if self.services.facebook_uploader:
            checks.append(bool(clip.facebook_video_id))
        return bool(checks) and all(checks)

    def _delete_published_clip_files(self, job: Job, clips: list[JobClip]) -> int:
        """Remove local MP4s/thumbnails of clips that are published on every platform.

        Files stay on disk while any enabled platform upload is still pending.
        """
        job_dir = self.settings.work_dir / "jobs" / job.id
        removed = 0
        for clip in clips:
            if not clip.output_path:
                continue
            if not self._clip_published_everywhere(clip):
                continue
            candidates = [
                Path(clip.output_path),
                job_dir / f"short-{clip.clip_index:03d}.mp4",
                job_dir / f"short-{clip.clip_index:03d}-enhanced.mp4",
            ]
            if clip.thumbnail_path:
                candidates.append(Path(clip.thumbnail_path))
            for candidate in candidates:
                candidate.unlink(missing_ok=True)
            self.repository.update_clip(
                job.id,
                clip.clip_index,
                output_path=None,
                thumbnail_path=None,
            )
            removed += 1
        return removed

    def _instagram_plan(self, plan: ShortPlan, sequence_index: int) -> ShortPlan:
        hashtag_pool = self.settings.instagram_hashtags()
        rotated_pool: list[str] = []
        if hashtag_pool:
            offset = (sequence_index * 30) % len(hashtag_pool)
            rotated_pool = hashtag_pool[offset:] + hashtag_pool[:offset]
        caption_rotation = self.settings.instagram_caption_rotation()
        caption_body = (
            caption_rotation[sequence_index % len(caption_rotation)]
            if caption_rotation
            else plan.instagram_caption
        )
        caption = apply_instagram_hashtags(
            caption_body,
            rotated_pool,
            self.settings.instagram_caption_target_chars,
            mentions=self.settings.instagram_mentions(),
            preserve_caption_hashtags=bool(caption_rotation),
        )
        return replace(plan, instagram_caption=caption)

    @staticmethod
    def _plan_from_clip(clip: JobClip) -> ShortPlan:
        return ShortPlan(
            start_seconds=clip.start_seconds,
            duration_seconds=clip.duration_seconds,
            title=clip.title,
            description=clip.description,
            instagram_caption=clip.instagram_caption,
        )

    async def _process_clip(
        self,
        job: Job,
        source: SourceVideo,
        clip: JobClip,
        total_clips: int,
        job_dir: Path,
        blocked_platforms: dict[str, str],
    ) -> JobClip:
        if self._clip_published_everywhere(clip):
            # Every enabled platform already has this clip; never re-render or re-upload it.
            return clip
        plan = self._plan_from_clip(clip)
        output_path = (
            Path(clip.output_path)
            if clip.output_path
            else (job_dir / f"short-{clip.clip_index:03d}.mp4")
        )
        if output_path.exists():
            try:
                existing_duration = await asyncio.to_thread(
                    self.services.media.probe_duration,
                    output_path,
                )
                if existing_duration < max(1, plan.duration_seconds - 1):
                    output_path.unlink(missing_ok=True)
            except WorkflowError:
                output_path.unlink(missing_ok=True)
        if not output_path.exists():
            await self._status(
                job.id,
                JobStatus.RENDERING,
                f"Rendering Short {clip.clip_index}/{total_clips}",
            )
            await asyncio.to_thread(
                self.services.media.render_short,
                source.path,
                output_path,
                plan.start_seconds,
                plan.duration_seconds,
            )
            clip = self.repository.update_clip(
                job.id,
                clip.clip_index,
                output_path=str(output_path),
                error=None,
            )

        enhance_this_clip = bool(
            self.services.enhancer
            and (
                self.settings.apimarket_max_clips == 0
                or clip.clip_index <= self.settings.apimarket_max_clips
            )
        )
        if enhance_this_clip and not clip.enhancement_complete:
            await self._status(
                job.id,
                JobStatus.RENDERING,
                f"Enhancing Short {clip.clip_index}/{total_clips} with Real-ESRGAN",
            )
            enhanced_path = job_dir / f"short-{clip.clip_index:03d}-enhanced.mp4"
            enhanced_path.unlink(missing_ok=True)
            assert self.services.enhancer is not None
            await self.services.enhancer.enhance(
                output_path,
                enhanced_path,
                public_id=f"soul_exter/{job.id}/clip-{clip.clip_index:03d}",
            )
            enhanced_duration = await asyncio.to_thread(
                self.services.media.probe_duration,
                enhanced_path,
            )
            if enhanced_duration < max(1, plan.duration_seconds - 1):
                enhanced_path.unlink(missing_ok=True)
                raise WorkflowError("Enhanced video is shorter than the rendered Short.")
            output_path = enhanced_path
            clip = self.repository.update_clip(
                job.id,
                clip.clip_index,
                output_path=str(output_path),
                enhancement_complete=1,
                error=None,
            )

        thumbnail_path = (
            Path(clip.thumbnail_path)
            if clip.thumbnail_path
            else (job_dir / f"thumbnail-{clip.clip_index:03d}.jpg")
        )
        if not thumbnail_path.exists():
            await asyncio.to_thread(
                self.services.media.generate_thumbnail,
                output_path,
                thumbnail_path,
                plan.duration_seconds / 2,
            )
            clip = self.repository.update_clip(
                job.id,
                clip.clip_index,
                thumbnail_path=str(thumbnail_path),
            )

        if (
            self.services.youtube_uploader
            and not clip.youtube_video_id
            and "YouTube" not in blocked_platforms
        ):
            await self._status(
                job.id,
                JobStatus.UPLOADING,
                f"Uploading Short {clip.clip_index}/{total_clips} to YouTube as "
                f"{self.settings.youtube_privacy_status}",
            )
            try:
                youtube_video_id = await self.services.youtube_uploader.upload(
                    output_path,
                    plan,
                    thumbnail_path,
                )
                clip = self.repository.update_clip(
                    job.id,
                    clip.clip_index,
                    youtube_video_id=youtube_video_id,
                    error=None,
                )
                if clip.clip_index == 1:
                    self.repository.update(job.id, youtube_video_id=youtube_video_id)
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    f"YouTube Short {clip.clip_index}/{total_clips} is public: "
                    f"https://www.youtube.com/shorts/{youtube_video_id}",
                )
            except UploadLimitError as exc:
                blocked_platforms["YouTube"] = str(exc)
                self.services.unavailable_platforms["YouTube"] = str(exc)
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    "YouTube limit reached",
                )
            except UploadError as exc:
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    f"YouTube Short {clip.clip_index}/{total_clips} failed; its upload remains "
                    f"pending, and the bot will continue with the next clip: {exc}",
                )

        if (
            self.services.instagram_uploader
            and not clip.instagram_media_id
            and "Instagram" not in blocked_platforms
        ):
            sequence_index = self.repository.clip_sequence_index(job.id, clip.clip_index)
            instagram_plan = self._instagram_plan(plan, sequence_index)
            if instagram_plan.instagram_caption != clip.instagram_caption:
                clip = self.repository.update_clip(
                    job.id,
                    clip.clip_index,
                    instagram_caption=instagram_plan.instagram_caption,
                )
                if clip.clip_index == 1:
                    self.repository.update(
                        job.id,
                        instagram_caption=instagram_plan.instagram_caption,
                    )
            await self._status(
                job.id,
                JobStatus.UPLOADING,
                f"Publishing Reel {clip.clip_index}/{total_clips} to Instagram",
            )
            try:
                instagram = await self.services.instagram_uploader.upload(
                    output_path, instagram_plan
                )
                clip = self.repository.update_clip(
                    job.id,
                    clip.clip_index,
                    instagram_media_id=instagram.media_id,
                    instagram_url=instagram.permalink,
                    error=None,
                )
                if clip.clip_index == 1:
                    self.repository.update(
                        job.id,
                        instagram_media_id=instagram.media_id,
                        instagram_url=instagram.permalink,
                    )
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    f"Instagram Reel {clip.clip_index}/{total_clips} is published: "
                    f"{instagram.permalink}",
                )
            except UploadLimitError as exc:
                blocked_platforms["Instagram"] = str(exc)
                self.services.unavailable_platforms["Instagram"] = str(exc)
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    "Instagram upload limit reached; continuing local generation",
                )
            except UploadError as exc:
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    f"Instagram Reel {clip.clip_index}/{total_clips} failed; its upload remains "
                    f"pending, and the bot will continue with the next Reel: {exc}",
                )

        if (
            self.services.facebook_uploader
            and not clip.facebook_video_id
            and "Facebook" not in blocked_platforms
        ):
            await self._status(
                job.id,
                JobStatus.UPLOADING,
                f"Publishing Reel {clip.clip_index}/{total_clips} to Facebook",
            )
            try:
                facebook_video_id, facebook_url = await self.services.facebook_uploader.upload(
                    output_path, plan
                )
                clip = self.repository.update_clip(
                    job.id,
                    clip.clip_index,
                    facebook_video_id=facebook_video_id,
                    facebook_url=facebook_url,
                    error=None,
                )
                if clip.clip_index == 1:
                    self.repository.update(
                        job.id,
                        facebook_video_id=facebook_video_id,
                        facebook_url=facebook_url,
                    )
                # A successful post means the platform is healthy again.
                self.services.platform_cooldowns.pop("Facebook", None)
                self.services.unavailable_platforms.pop("Facebook", None)
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    f"Facebook Reel {clip.clip_index}/{total_clips} is published: {facebook_url}",
                )
            except UploadLimitError as exc:
                blocked_platforms["Facebook"] = str(exc)
                self.services.unavailable_platforms["Facebook"] = str(exc)
                self.services.platform_cooldowns["Facebook"] = (
                    time.monotonic() + self.settings.facebook_limit_cooldown_hours * 3600
                )
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    f"Facebook upload limit reached; pausing Facebook for "
                    f"{self.settings.facebook_limit_cooldown_hours:g}h to let the limit "
                    f"lift, then it will retry automatically: {exc}",
                )
            except UploadError as exc:
                await self._status(
                    job.id,
                    JobStatus.UPLOADING,
                    f"Facebook Reel {clip.clip_index}/{total_clips} failed; its upload remains "
                    f"pending, and the bot will continue with the next Reel: {exc}",
                )
        return clip

    @staticmethod
    def _has_legacy_render(job: Job) -> bool:
        return bool(job.output_path and job.short_title and Path(job.output_path).exists())

    async def _resume_legacy_render(self, job: Job) -> Job:
        output_path = Path(job.output_path or "")
        duration = await asyncio.to_thread(self.services.media.probe_duration, output_path)
        plan = ShortPlan(
            start_seconds=0,
            duration_seconds=min(30, duration),
            title=job.short_title or "YouTube Short #Shorts",
            description=job.short_description or "#Shorts",
            instagram_caption=job.instagram_caption or "#Reels",
        )
        youtube_video_id = job.youtube_video_id
        instagram_media_id = job.instagram_media_id
        instagram_url = job.instagram_url
        instagram_caption = plan.instagram_caption
        facebook_video_id = job.facebook_video_id
        facebook_url = job.facebook_url

        if self.services.youtube_uploader and not youtube_video_id:
            await self._status(job.id, JobStatus.UPLOADING, "Uploading existing Short to YouTube")
            youtube_video_id = await self.services.youtube_uploader.upload(output_path, plan)
        if self.services.instagram_uploader and not instagram_media_id:
            await self._status(
                job.id,
                JobStatus.UPLOADING,
                "Publishing existing Short to Instagram",
            )
            instagram_plan = self._instagram_plan(plan, 0)
            instagram_caption = instagram_plan.instagram_caption
            instagram = await self.services.instagram_uploader.upload(output_path, instagram_plan)
            instagram_media_id = instagram.media_id
            instagram_url = instagram.permalink
        if self.services.facebook_uploader and not facebook_video_id:
            await self._status(
                job.id,
                JobStatus.UPLOADING,
                "Publishing existing Short to Facebook",
            )
            facebook_video_id, facebook_url = await self.services.facebook_uploader.upload(
                output_path, plan
            )

        platforms = self._configured_platforms()
        completed = self.repository.update(
            job.id,
            status=JobStatus.COMPLETE,
            progress_message=(
                f"Published existing Short to {' and '.join(platforms)}"
                if platforms
                else "Existing Short is ready"
            ),
            youtube_video_id=youtube_video_id,
            instagram_media_id=instagram_media_id,
            instagram_url=instagram_url,
            instagram_caption=instagram_caption,
            facebook_video_id=facebook_video_id,
            facebook_url=facebook_url,
            error=None,
        )
        await self._notify(completed, completed.progress_message)
        return completed

    async def _load_existing_source(self, job: Job, job_dir: Path) -> SourceVideo:
        candidates = [
            path
            for path in job_dir.glob("source.*")
            if path.is_file() and path.suffix not in {".json", ".part", ".ytdl"}
        ]
        if not candidates:
            raise WorkflowError(
                f"Job {job.id} has no completed source download to resume. Add its URL "
                "back to links.txt instead."
            )
        source_path = max(candidates, key=lambda path: path.stat().st_size)

        metadata: dict[str, object] = {}
        info_files = list(job_dir.glob("source*.info.json"))
        if info_files:
            try:
                metadata = json.loads(info_files[0].read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("Could not read source metadata for resumed job %s", job.id)

        duration = float(metadata.get("duration") or 0)
        if duration <= 0:
            duration = await asyncio.to_thread(self.services.media.probe_duration, source_path)

        return SourceVideo(
            path=source_path,
            source_url=str(metadata.get("webpage_url") or job.source_url),
            video_id=str(metadata.get("id") or "unknown"),
            title=str(metadata.get("title") or job.source_title or "Untitled video"),
            uploader=str(metadata.get("uploader") or metadata.get("channel") or "Original creator"),
            duration_seconds=duration,
        )

    async def _status(self, job_id: str, status: JobStatus, message: str) -> Job:
        job = self.repository.update(
            job_id,
            status=status,
            progress_message=message,
            error=None,
        )
        await self._notify(job, message)
        return job

    async def _notify(self, job: Job, message: str) -> None:
        if not self.on_status:
            return
        try:
            await self.on_status(job, message)
        except Exception:
            logger.exception("Could not send status notification for job %s", job.id)


class JobQueue:
    def __init__(self, pipeline: WorkflowPipeline) -> None:
        self.pipeline = pipeline
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.worker_task or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker(), name="shorts-workflow-worker")

    async def stop(self) -> None:
        if not self.worker_task:
            return
        self.worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await self.worker_task
        self.worker_task = None

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self.pipeline.process(job_id)
            except Exception:
                logger.exception("Unexpected queue failure for job %s", job_id)
            finally:
                self.queue.task_done()


def _safe_error(exc: Exception) -> str:
    message = " ".join(str(exc).split()) or exc.__class__.__name__
    return message[:1500]
