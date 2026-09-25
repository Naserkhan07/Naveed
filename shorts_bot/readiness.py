"""Helpers for measuring the finished-clip buffer and work already in flight."""

from __future__ import annotations

from .config import Settings
from .db import JobRepository

_SOURCE_EXTENSIONS = {".mkv", ".mov", ".mp4"}


def finished_ready_clip_count(settings: Settings, repository: JobRepository) -> int:
    """Count clips still available to every enabled platform.

    A clip counts as ready only while it is pending on all enabled platforms.
    That keeps the buffer useful for a multi-platform schedule instead of
    counting a clip that has already been published to one destination.
    """
    enabled = settings.enabled_platforms()
    if not enabled:
        return 0
    pending = repository.pending_publication_counts()
    return min(pending[name] for name in enabled)


def ready_buffer_occupancy(settings: Settings, repository: JobRepository) -> int:
    """Estimate ready plus staged work so source discovery does not overfill.

    Finished queued clips are counted once, along with exports not yet enrolled
    in SQLite and source files waiting for HotClip. An in-flight source counts
    as one clip conservatively; HotClip may produce more than one clip from it.
    """
    occupancy = finished_ready_clip_count(settings, repository)

    if settings.hotclip_export_dir.is_dir():
        enrolled_paths = repository.publication_paths()
        for path in settings.hotclip_export_dir.rglob("*.mp4"):
            if path.is_file() and str(path) not in enrolled_paths:
                occupancy += 1

    if settings.hotclip_watch_dir.is_dir():
        for path in settings.hotclip_watch_dir.iterdir():
            if (
                path.is_file()
                and path.suffix.casefold() in _SOURCE_EXTENSIONS
                and not path.with_name(f"{path.name}.clipped").exists()
            ):
                occupancy += 1

    return occupancy
