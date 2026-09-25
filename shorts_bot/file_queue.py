from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from .channels import ChannelVideo, discover_new_videos
from .config import Settings
from .db import JobRepository
from .downloader import is_youtube_url
from .errors import ConfigurationError, WorkflowError
from .models import ChannelPlatform, Job, SourceVideo
from .pipeline import WorkflowPipeline, WorkflowServices
from .publisher import publish_platform_due, run_due_publishes

_PLATFORMS = {
    "youtube": ChannelPlatform.YOUTUBE,
    "instagram": ChannelPlatform.INSTAGRAM,
    "facebook": ChannelPlatform.FACEBOOK,
}


class LinkFileQueue:
    """A line-based URL queue with atomic acknowledgement after download."""

    def __init__(self, links_file: Path, downloaded_log: Path) -> None:
        self.links_file = links_file
        self.downloaded_log = downloaded_log

    def pending_urls(self) -> list[str]:
        lines = self.links_file.read_text(encoding="utf-8").splitlines()
        urls: list[str] = []
        for line in lines:
            candidate = line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            if is_youtube_url(candidate) and candidate not in urls:
                urls.append(candidate)
            else:
                print(
                    f"Ignoring invalid or duplicate links.txt entry: {candidate}", file=sys.stderr
                )
        return urls

    def acknowledge_download(self, url: str, job: Job, source: SourceVideo) -> None:
        """Remove the first exact URL line and record it; leave comments and new URLs intact."""
        original_lines = self.links_file.read_text(encoding="utf-8").splitlines(keepends=True)
        output_lines: list[str] = []
        removed = False
        for line in original_lines:
            if line.strip() == url:
                removed = True
                continue
            output_lines.append(line)
        if not removed:
            raise WorkflowError(
                f"Downloaded {url}, but its line disappeared before it could be acknowledged."
            )

        temporary = self.links_file.with_name(f".{self.links_file.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text("".join(output_lines), encoding="utf-8")
            os.replace(temporary, self.links_file)
        finally:
            temporary.unlink(missing_ok=True)

        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        safe_title = " ".join(source.title.split()).replace("\t", " ")
        with self.downloaded_log.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{timestamp}\t{job.id}\t{url}\t{safe_title}\n")


async def run_file_queue(
    settings: Settings,
    watch: bool = True,
    resume_job_id: str | None = None,
    expand_job_id: str | None = None,
    rebuild_job_id: str | None = None,
    scan_only: bool = False,
) -> int:
    settings.validate_file_queue()
    settings.prepare_directories()
    repository = JobRepository(settings.database_path)
    repository.fail_interrupted()
    services = WorkflowServices.from_settings(settings)
    services.media.check_tools()
    link_queue = LinkFileQueue(settings.links_file, settings.downloaded_links_log)

    async def report(job: Job, message: str) -> None:
        print(f"[{job.id}] {job.status.value}: {message}", flush=True)

    async def downloaded(job: Job, source: SourceVideo) -> None:
        # Channel-discovered URLs are not in links.txt; only file entries are acked.
        if job.source_url in link_queue.pending_urls():
            link_queue.acknowledge_download(job.source_url, job, source)
            print(f"[{job.id}] removed downloaded URL from {settings.links_file}", flush=True)

    pipeline = WorkflowPipeline(
        settings,
        repository,
        services,
        on_status=report,
        on_downloaded=downloaded,
    )

    async def run_preflight() -> bool:
        try:
            report_lines = await services.preflight()
        except WorkflowError as exc:
            print(f"Credential check failed: {exc}", file=sys.stderr, flush=True)
            return False
        print("Credential report: " + " | ".join(report_lines), flush=True)
        return True

    workflow_ready = await run_preflight()
    selected_job_id = rebuild_job_id or expand_job_id or resume_job_id
    if selected_job_id:
        if not workflow_ready:
            return 1
        job = repository.get(selected_job_id)
        if not job:
            print(
                f"Job {selected_job_id} was not found in {settings.database_path}.", file=sys.stderr
            )
            return 1
        if rebuild_job_id:
            previous_clips = repository.reset_clip_media(job.id)
            if not previous_clips:
                print(
                    f"Job {job.id} has no multi-clip batch to rebuild; use --expand first.",
                    file=sys.stderr,
                )
                return 1
            for clip in previous_clips:
                for path_value in (clip.output_path, clip.thumbnail_path):
                    if path_value:
                        Path(path_value).unlink(missing_ok=True)
            job_dir = settings.work_dir / "jobs" / job.id
            for pattern in ("short-*.mp4", "thumbnail-*.jpg"):
                for stale_file in job_dir.glob(pattern):
                    stale_file.unlink(missing_ok=True)
            action = "regenerating metadata, rebuilding, and re-uploading every clip"
        elif expand_job_id:
            action = "expanding into multiple clips"
        else:
            action = "resuming"
        print(f"[{job.id}] reusing its existing downloaded source and {action}", flush=True)
        result = await pipeline.process(
            job.id,
            reuse_downloaded=True,
            expand_existing=bool(expand_job_id),
        )
        return 1 if result.error else 0

    failed_urls_this_session: set[str] = set()
    if watch:
        print(
            f"Local watcher started. Add YouTube URLs to {settings.links_file}. "
            "Press Ctrl+C to stop.",
            flush=True,
        )

    async def retry_pending_jobs() -> None:
        counts = repository.pending_upload_counts()
        print(
            "Pending upload report: "
            + " | ".join(f"{platform}: {count}" for platform, count in counts.items()),
            flush=True,
        )
        youtube_ready = bool(
            settings.upload_youtube and services.platform_unavailable("YouTube") is None
        )
        instagram_ready = bool(
            settings.upload_instagram and services.platform_unavailable("Instagram") is None
        )
        facebook_ready = bool(
            settings.upload_facebook and services.platform_unavailable("Facebook") is None
        )
        pending_jobs = repository.list_pending_upload_jobs(
            youtube=youtube_ready,
            instagram=instagram_ready,
            facebook=facebook_ready,
            limit=settings.pending_retry_jobs_per_cycle,
        )
        for pending_job in pending_jobs:
            print(
                f"[{pending_job.id}] automatically retrying pending platform uploads",
                flush=True,
            )
            await pipeline.process(pending_job.id, reuse_downloaded=True)

    next_credential_check = time.monotonic() + settings.credential_check_minutes * 60
    next_pending_retry = time.monotonic()
    next_channel_scan = time.monotonic()

    async def process_source_url(
        url: str,
        channel_video: ChannelVideo | None = None,
    ) -> bool:
        job = repository.create(chat_id=0, user_id=0, source_url=url)
        if channel_video is not None:
            repository.mark_channel_video_queued(
                channel_video.channel_key,
                channel_video.video_id,
                channel_video.url,
                channel_video.title,
                job.id,
            )
        result = await pipeline.process(job.id)
        if result.error:
            failed_urls_this_session.add(url)
            if watch:
                print(
                    f"[{job.id}] URL will not retry again in this session. "
                    "It remains queued and will retry after the next credential cycle.",
                    flush=True,
                )
            return False
        return True

    async def scan_channels_once() -> bool:
        if not settings.channels_file.exists():
            return False
        new_videos, errors = await asyncio.to_thread(
            discover_new_videos,
            settings.channels_file,
            repository,
            settings.channel_scan_max_videos,
        )
        for message in errors:
            print(message, file=sys.stderr, flush=True)
        processed = False
        for video in new_videos:
            if video.url in failed_urls_this_session:
                continue
            processed = True
            print(
                f"[channel] new upload from {video.channel_key}: {video.title} ({video.url})",
                flush=True,
            )
            if not await process_source_url(video.url, channel_video=video):
                return processed
        return processed

    async def publish_scheduled_uploads() -> None:
        if not settings.scheduled_platforms:
            return
        published = await run_due_publishes(
            settings,
            repository,
            services,
            on_status=lambda message: print(f"[scheduler] {message}", flush=True),
        )
        for clip in published:
            print(
                f"[scheduler] published clip {clip.clip_index} of job {clip.job_id}",
                flush=True,
            )

    if scan_only:
        await scan_channels_once()
        await publish_scheduled_uploads()
        return 1 if failed_urls_this_session else 0

    while True:
        if not workflow_ready or time.monotonic() >= next_credential_check:
            try:
                refreshed = Settings.from_env(override=True)
                refreshed.validate_file_queue()
                refreshed.prepare_directories()
                refreshed_services = WorkflowServices.from_settings(refreshed)
                refreshed_services.media.check_tools()
                refreshed_report = await refreshed_services.preflight()
                settings = refreshed
                services = refreshed_services
                link_queue = LinkFileQueue(settings.links_file, settings.downloaded_links_log)
                pipeline = WorkflowPipeline(
                    settings,
                    repository,
                    services,
                    on_status=report,
                    on_downloaded=downloaded,
                )
                workflow_ready = True
                failed_urls_this_session.clear()
                print("Credential report: " + " | ".join(refreshed_report), flush=True)
                next_credential_check = time.monotonic() + settings.credential_check_minutes * 60
                next_pending_retry = min(next_pending_retry, time.monotonic())
            except (ConfigurationError, WorkflowError) as exc:
                workflow_ready = False
                print(
                    f"Credential refresh failed; retrying automatically: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                next_credential_check = time.monotonic() + 300

        if not workflow_ready:
            if not watch:
                return 1
            await asyncio.sleep(min(settings.links_poll_seconds, 30))
            continue

        urls = link_queue.pending_urls()
        processed_new_url = False
        for url in urls:
            if url in failed_urls_this_session:
                continue
            processed_new_url = True
            await process_source_url(url)

        if time.monotonic() >= next_channel_scan:
            if await scan_channels_once():
                processed_new_url = True
            next_channel_scan = time.monotonic() + settings.channel_scan_interval_minutes * 60

        if not processed_new_url and time.monotonic() >= next_pending_retry:
            await retry_pending_jobs()
            next_pending_retry = time.monotonic() + settings.credential_check_minutes * 60

        await publish_scheduled_uploads()

        if not watch:
            return 1 if failed_urls_this_session else 0
        await asyncio.sleep(settings.links_poll_seconds)


async def run_scheduled_publish(settings: Settings, platform: ChannelPlatform) -> int:
    """One-shot scheduled publisher used by the per-platform cron jobs."""
    settings.validate_file_queue()
    settings.prepare_directories()
    repository = JobRepository(settings.database_path)
    services = WorkflowServices.from_settings(settings)
    await publish_platform_due(
        settings,
        repository,
        services,
        platform,
        on_status=lambda message: print(f"[scheduler] {message}", flush=True),
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Watch links.txt and publish multiple AI-selected YouTube Shorts and/or "
            "Instagram Reels from each downloaded video."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Process the current file once and exit instead of watching it",
    )
    mode.add_argument(
        "--resume",
        metavar="JOB_ID",
        help="Reuse a previously downloaded source and retry unfinished stages",
    )
    mode.add_argument(
        "--expand",
        metavar="JOB_ID",
        help="Turn a legacy single-clip job into a new multi-clip batch",
    )
    mode.add_argument(
        "--rebuild",
        metavar="JOB_ID",
        help="Re-render and re-upload every clip using current quality settings",
    )
    mode.add_argument(
        "--publish",
        metavar="PLATFORM",
        choices=sorted(_PLATFORMS),
        help=(
            "Publish due scheduled uploads for one platform (youtube, instagram, "
            "facebook) and exit. Used by the per-platform schedulers."
        ),
    )
    mode.add_argument(
        "--scan-channels",
        action="store_true",
        help="Only scan channels.txt for new uploads, process them, then exit",
    )
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if args.publish:
            exit_code = asyncio.run(
                run_scheduled_publish(settings, _PLATFORMS[args.publish])
            )
        else:
            exit_code = asyncio.run(
                run_file_queue(
                    settings,
                    watch=not args.once
                    and not args.resume
                    and not args.expand
                    and not args.rebuild
                    and not args.scan_channels,
                    resume_job_id=args.resume,
                    expand_job_id=args.expand,
                    rebuild_job_id=args.rebuild,
                    scan_only=args.scan_channels,
                )
            )
    except ConfigurationError as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        print("\nLocal watcher stopped.")
        exit_code = 0
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
