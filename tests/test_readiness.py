from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shorts_bot.config import Settings
from shorts_bot.db import JobRepository
from shorts_bot.readiness import finished_ready_clip_count, ready_buffer_occupancy


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base = Settings.from_env(env_file=None)
    return replace(
        base,
        database_path=tmp_path / "work" / "jobs.db",
        hotclip_watch_dir=tmp_path / "watch",
        hotclip_export_dir=tmp_path / "exports",
        upload_youtube=True,
        upload_instagram=False,
        upload_facebook=True,
        **overrides,  # type: ignore[arg-type]
    )


def test_ready_buffer_counts_clips_pending_on_every_enabled_platform(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = JobRepository(settings.database_path)
    settings.hotclip_export_dir.mkdir(parents=True)

    both_pending = settings.hotclip_export_dir / "both-pending.mp4"
    both_pending.write_bytes(b"clip")
    repository.add_publication(both_pending, title="Pending everywhere")

    partly_published = settings.hotclip_export_dir / "partly-published.mp4"
    partly_published.write_bytes(b"clip")
    publication = repository.add_publication(partly_published, title="Already on YouTube")
    repository.update_publication(
        publication.id,
        youtube_video_id="published-youtube",
        youtube_uploaded_at="2026-09-25T10:00:00+00:00",
    )

    assert finished_ready_clip_count(settings, repository) == 1
    # The partial publication is not counted as ready for all enabled destinations.
    assert ready_buffer_occupancy(settings, repository) == 1


def test_ready_buffer_includes_unqueued_exports_and_unclipped_sources(tmp_path: Path) -> None:
    settings = replace(_settings(tmp_path), upload_facebook=False)
    repository = JobRepository(settings.database_path)
    settings.hotclip_export_dir.mkdir(parents=True)
    settings.hotclip_watch_dir.mkdir(parents=True)

    queued = settings.hotclip_export_dir / "queued.mp4"
    queued.write_bytes(b"queued")
    repository.add_publication(queued, title="Already in the queue")

    unqueued = settings.hotclip_export_dir / "not-yet-queued.mp4"
    unqueued.write_bytes(b"new export")
    source = settings.hotclip_watch_dir / "source.mkv"
    source.write_bytes(b"source")
    clipped_source = settings.hotclip_watch_dir / "already-clipped.mp4"
    clipped_source.write_bytes(b"source")
    clipped_source.with_name(f"{clipped_source.name}.clipped").touch()

    assert finished_ready_clip_count(settings, repository) == 1
    assert ready_buffer_occupancy(settings, repository) == 3
