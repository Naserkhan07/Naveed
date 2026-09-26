from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from shorts_bot.config import Settings
from shorts_bot.db import JobRepository
from shorts_bot.file_queue import (
    HotClipCoordinator,
    LinkFileQueue,
    _safe_stem,
    parse_stages,
    run_file_queue,
)
from shorts_bot.models import SourceVideo
from shorts_bot.publisher import Publisher

WORK = "https://youtu.be/example"


class FakeDownloader:
    def __init__(self) -> None:
        self.downloads: list[str] = []

    async def download(self, url: str, destination: Path) -> SourceVideo:
        self.downloads.append(url)
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f"{_safe_stem(url, 'video')}.mp4"
        path.write_bytes(b"source")
        return SourceVideo(path, url, "abc123", "Some Title", "Creator", 300)


def _settings(tmp_path: Path) -> Settings:
    base = Settings.from_env(env_file=None)
    return replace(
        base,
        work_dir=tmp_path / "work",
        database_path=tmp_path / "work" / "jobs.db",
        links_file=tmp_path / "links.txt",
        downloaded_links_log=tmp_path / "work" / "downloaded-links.log",
        channels_file=tmp_path / "channels.txt",
        hotclip_watch_dir=tmp_path / "watch",
        hotclip_export_dir=tmp_path / "exports",
    )


def test_acknowledges_download_atomically_and_preserves_comments(tmp_path: Path) -> None:
    links_file = tmp_path / "links.txt"
    links_file.write_text(
        f"# keep me\n{WORK}\n\nhttps://youtu.be/other\n",
        encoding="utf-8",
    )
    queue = LinkFileQueue(links_file, tmp_path / "download.log")
    assert queue.pending_urls() == [WORK, "https://youtu.be/other"]

    queue.acknowledge_download(WORK, "video.mp4")
    assert queue.pending_urls() == ["https://youtu.be/other"]
    text = links_file.read_text(encoding="utf-8")
    assert "# keep me" in text and "https://youtu.be/other" in text
    assert WORK in (tmp_path / "download.log").read_text(encoding="utf-8")
    assert "video.mp4" in (tmp_path / "download.log").read_text(encoding="utf-8")


async def test_deliver_source_moves_download_into_watch_dir(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = JobRepository(settings.database_path)
    coordinator = HotClipCoordinator(settings, repository, FakeDownloader())  # type: ignore[arg-type]

    destination = await coordinator.deliver_source(WORK, "My Video")
    assert destination is not None
    assert destination.parent == settings.hotclip_watch_dir
    assert destination.read_bytes() == b"source"
    assert "My-Video" in destination.name
    # The staging directory was cleaned up.
    assert not (settings.work_dir / "incoming").exists() or not any(
        (settings.work_dir / "incoming").iterdir()
    )


async def test_deliver_source_skips_when_watch_copy_exists(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = JobRepository(settings.database_path)
    coordinator = HotClipCoordinator(settings, repository, FakeDownloader())  # type: ignore[arg-type]

    first = await coordinator.deliver_source(WORK, "My Video")
    assert first is not None
    assert first.read_bytes() == b"source"
    # A second delivery of the same destination name is skipped, not overwritten.
    first.write_bytes(b"edited")
    second = await coordinator.deliver_source(WORK, "My Video")
    assert second is None
    assert first.read_bytes() == b"edited"


async def test_intake_exports_enrolls_new_clips_once(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = JobRepository(settings.database_path)
    coordinator = HotClipCoordinator(settings, repository, FakeDownloader())  # type: ignore[arg-type]

    import os
    import time as time_mod

    export = settings.hotclip_export_dir / "clip-01.mp4"
    export.parent.mkdir(parents=True, exist_ok=True)
    export.write_bytes(b"clip")
    old = time_mod.time() - 180
    os.utime(export, (old, old))

    added = await coordinator.intake_exports()
    assert added == 1
    publications = repository.list_publications()
    assert len(publications) == 1
    assert publications[0].mp4_path == str(export)

    # Second intake does not duplicate.
    assert await coordinator.intake_exports() == 0
    assert len(repository.list_publications()) == 1


def test_safe_stem() -> None:
    assert _safe_stem("Hello, World!") == "Hello-World"
    assert _safe_stem("") == "video"


async def test_channel_scan_skips_discovery_when_ready_buffer_is_full(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = replace(
        _settings(tmp_path),
        rights_acknowledged=True,
        ready_clip_buffer_target=1,
    )
    settings.channels_file.write_text("@authorized-creator\n", encoding="utf-8")
    settings.hotclip_export_dir.mkdir(parents=True, exist_ok=True)
    clip = settings.hotclip_export_dir / "ready.mp4"
    clip.write_bytes(b"clip")
    repository = JobRepository(settings.database_path)
    repository.add_publication(clip, title="Ready clip")

    def fail_if_discovered(*args: object, **kwargs: object) -> tuple[list[object], list[str]]:
        raise AssertionError("channel discovery should be skipped for a full buffer")

    monkeypatch.setattr("shorts_bot.file_queue.discover_new_videos", fail_if_discovered)
    result = await run_file_queue(
        settings,
        watch=False,
        stages=frozenset({"channels"}),
    )

    assert result == 0


async def test_full_cycle_publishes_before_slow_source_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = tmp_path / "youtube-token.json"
    token.write_text("{}", encoding="utf-8")
    settings = replace(
        _settings(tmp_path),
        rights_acknowledged=True,
        upload_youtube=True,
        youtube_channel_id="UC" + "a" * 22,
        youtube_token_file=token,
        upload_instagram=False,
        upload_facebook=False,
    )
    events: list[str] = []

    async def fake_publish_all_due(self, report=None) -> None:  # noqa: ANN001
        events.append("publish")

    def fake_pending_urls(self) -> list[str]:  # noqa: ANN001
        events.append("download")
        return []

    monkeypatch.setattr(Publisher, "publish_all_due", fake_publish_all_due)
    monkeypatch.setattr(LinkFileQueue, "pending_urls", fake_pending_urls)

    result = await run_file_queue(
        settings,
        watch=False,
        stages=frozenset({"download", "publish"}),
    )

    assert result == 0
    assert events == ["publish", "download"]


def test_parse_stages_defaults_to_everything_and_validates() -> None:
    assert parse_stages("") == frozenset({"download", "channels", "intake", "publish"})
    assert parse_stages("download, publish") == frozenset({"download", "publish"})
    assert parse_stages("DOWNLOAD") == frozenset({"download"})
    with pytest.raises(ValueError, match="Unknown stage"):
        parse_stages("download,nope")
