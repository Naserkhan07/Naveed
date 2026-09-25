from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from .channels import discover_new_videos
from .config import Settings
from .db import JobRepository
from .downloader import VideoDownloader, is_youtube_url
from .errors import ConfigurationError, WorkflowError
from .hotclip import scan_export_dir
from .models import ChannelPlatform
from .publisher import Publisher

logger = logging.getLogger(__name__)

_PLATFORMS = {
    "youtube": ChannelPlatform.YOUTUBE,
    "instagram": ChannelPlatform.INSTAGRAM,
    "facebook": ChannelPlatform.FACEBOOK,
}

_SAFE_NAME = re.compile(r"[^\w.-]+")


def _safe_stem(value: str, fallback: str = "video") -> str:
    cleaned = _SAFE_NAME.sub("-", value).strip("-._")
    return cleaned[:60] or fallback


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

    def acknowledge_download(self, url: str, label: str) -> None:
        """Remove the first exact URL line and record it; leave comments intact."""
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
        with self.downloaded_log.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{timestamp}\t{url}\t{label}\n")


class HotClipCoordinator:
    """Feeds downloaded sources to HotClip and harvests its finished clips."""

    def __init__(
        self,
        settings: Settings,
        repository: JobRepository,
        downloader: VideoDownloader,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.downloader = downloader

    async def deliver_source(self, url: str, source_label: str = "") -> Path | None:
        """Download one video straight into HotClip's watch folder."""
        staging = self.settings.work_dir / "incoming"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            source = await self.downloader.download(url, staging)
        except WorkflowError as exc:
            print(f"Download failed for {url}: {exc}", file=sys.stderr, flush=True)
            return None
        label = source_label or source.title
        suffix = source.path.suffix or ".mp4"
        destination = self.settings.hotclip_watch_dir / (
            f"{_safe_stem(label)}__{_safe_stem(source.video_id, 'id')}{suffix}"
        )
        if destination.exists():
            print(f"HotClip watch folder already has {destination.name}; skipping.", flush=True)
            source.path.unlink(missing_ok=True)
            return None
        self.settings.hotclip_watch_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(source.path, destination)
        except OSError:
            import shutil

            shutil.move(str(source.path), destination)
        print(f"[{label}] handed to HotClip: {destination}", flush=True)
        with suppress(OSError):
            source.path.parent.rmdir()
        return destination

    async def intake_exports(self) -> int:
        """Queue newly finished HotClip exports for publishing."""
        clips = await asyncio.to_thread(
            scan_export_dir,
            self.settings.hotclip_export_dir,
            None,
            self.settings.hotclip_min_clip_age_seconds,
        )
        added = 0
        for clip in clips:
            if self.repository.publication_exists(clip.mp4_path):
                continue
            title = clip.title or clip.mp4_path.stem
            description = clip.description or title
            caption = clip.instagram_caption or title
            self.repository.add_publication(
                clip.mp4_path,
                title=title[:450],
                description=description[: self.settings.youtube_description_target_chars],
                instagram_caption=caption[: self.settings.instagram_caption_target_chars],
                cover_path=clip.cover_path,
                source_label=clip.source_label,
            )
            added += 1
            print(f"[intake] queued new clip for publishing: {title}", flush=True)
        return added


async def run_file_queue(
    settings: Settings,
    watch: bool = True,
    scan_only: bool = False,
) -> int:
    settings.validate_queue()
    settings.prepare_directories()
    for warning in settings.quota_warnings():
        print(f"Quota warning: {warning}", file=sys.stderr, flush=True)

    repository = JobRepository(settings.database_path)
    downloader = VideoDownloader(
        cookies_from_browser=settings.ytdlp_cookies_from_browser,
        browser_profile=settings.ytdlp_browser_profile,
        cookie_file=settings.ytdlp_cookie_file,
    )
    coordinator = HotClipCoordinator(settings, repository, downloader)
    publisher = Publisher(settings, repository)
    link_queue = LinkFileQueue(settings.links_file, settings.downloaded_links_log)

    if watch:
        print(
            "Watcher started. Feed sources through links.txt and channels.txt; "
            "HotClip makes the clips; the scheduler publishes them. Ctrl+C to stop.",
            flush=True,
        )

    failures: set[str] = set()
    next_channel_scan = time.monotonic()

    async def process_links() -> bool:
        processed = False
        for url in link_queue.pending_urls():
            if url in failures:
                continue
            processed = True
            destination = await coordinator.deliver_source(url)
            if destination is None:
                failures.add(url)
                print(f"[links] {url} failed; it stays in links.txt for a retry.", flush=True)
                continue
            link_queue.acknowledge_download(url, destination.name)
        return processed

    async def process_channels() -> bool:
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
            if video.url in failures:
                continue
            processed = True
            print(
                f"[channel] new upload from {video.channel_key}: {video.title} ({video.url})",
                flush=True,
            )
            destination = await coordinator.deliver_source(video.url, video.title)
            if destination is None:
                failures.add(video.url)
                continue
            repository.mark_channel_video_queued(
                video.channel_key,
                video.video_id,
                video.url,
                video.title,
            )
        return processed

    async def intake_and_publish() -> None:
        added = await coordinator.intake_exports()
        counts = repository.pending_publication_counts()
        total = sum(counts.values())
        if added or total:
            print(
                f"[queue] {added} new clip(s) grabbed from HotClip exports; "
                + " | ".join(f"{name}: {count}" for name, count in counts.items()),
                flush=True,
            )
        await publisher.publish_all_due(
            report=lambda message: print(f"[scheduler] {message}", flush=True)
        )

    if scan_only:
        await process_channels()
        return 1 if failures else 0

    while True:
        try:
            await process_links()
            if time.monotonic() >= next_channel_scan:
                await process_channels()
                next_channel_scan = (
                    time.monotonic() + settings.channel_scan_interval_minutes * 60
                )
            await intake_and_publish()
        except ConfigurationError as exc:
            print(f"Configuration problem: {exc}", file=sys.stderr, flush=True)
            if not watch:
                return 1

        if not watch:
            return 1 if failures else 0
        await asyncio.sleep(settings.links_poll_seconds)


async def run_scheduled_publish(settings: Settings, platform: ChannelPlatform) -> int:
    """One-shot scheduled publisher for per-platform cron jobs."""
    settings.validate_queue()
    settings.prepare_directories()
    repository = JobRepository(settings.database_path)
    publisher = Publisher(settings, repository)
    await publisher.publish_due(
        platform,
        report=lambda message: print(f"[scheduler] {message}", flush=True),
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Hand new YouTube videos to HotClip (clipping/captions), harvest the "
            "finished clips, and publish them on each platform's schedule."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Run one full cycle (links, channels, intake, due uploads) and exit",
    )
    mode.add_argument(
        "--publish",
        metavar="PLATFORM",
        choices=sorted(_PLATFORMS),
        help=(
            "Publish due scheduled uploads for one platform (youtube, instagram, "
            "facebook) and exit. Used by per-platform schedulers."
        ),
    )
    mode.add_argument(
        "--scan-channels",
        action="store_true",
        help="Only scan channels.txt for new uploads and hand them to HotClip, then exit",
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
                    watch=not args.once and not args.scan_channels,
                    scan_only=args.scan_channels,
                )
            )
    except ConfigurationError as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        print("\nWatcher stopped.")
        exit_code = 0
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
