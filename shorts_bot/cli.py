from __future__ import annotations

import argparse
import asyncio

from .config import Settings
from .db import JobRepository
from .downloader import VideoDownloader, is_youtube_url
from .errors import ConfigurationError
from .file_queue import HotClipCoordinator


async def _run(urls: list[str]) -> int:
    settings = Settings.from_env()
    settings.validate_queue()
    settings.prepare_directories()

    repository = JobRepository(settings.database_path)
    coordinator = HotClipCoordinator(
        settings,
        repository,
        VideoDownloader(
            cookies_from_browser=settings.ytdlp_cookies_from_browser,
            browser_profile=settings.ytdlp_browser_profile,
            cookie_file=settings.ytdlp_cookie_file,
        ),
    )
    failed = False
    for url in urls:
        if not is_youtube_url(url):
            print(f"Skipping unsupported URL: {url}")
            failed = True
            continue
        destination = await coordinator.deliver_source(url)
        if destination is None:
            failed = True
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download authorized YouTube videos straight into HotClip's watch "
            "folder so it can clip, caption, and render them."
        )
    )
    parser.add_argument("urls", nargs="+", help="Individual YouTube video URLs")
    args = parser.parse_args()
    try:
        exit_code = asyncio.run(_run(args.urls))
    except ConfigurationError as exc:
        parser.error(str(exc))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
