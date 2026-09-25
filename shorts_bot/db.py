from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    ChannelPlatform,
    Job,
    JobClip,
    JobStatus,
    ShortPlan,
    platform_column,
    platform_uploaded_at_column,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL,
    progress_message TEXT NOT NULL DEFAULT '',
    source_title TEXT,
    short_title TEXT,
    short_description TEXT,
    instagram_caption TEXT,
    output_path TEXT,
    youtube_video_id TEXT,
    instagram_media_id TEXT,
    instagram_url TEXT,
    facebook_video_id TEXT,
    facebook_url TEXT,
    archive_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS job_clips (
    job_id TEXT NOT NULL,
    clip_index INTEGER NOT NULL,
    start_seconds REAL NOT NULL,
    duration_seconds REAL NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    instagram_caption TEXT NOT NULL,
    metadata_ready INTEGER NOT NULL DEFAULT 0,
    enhancement_complete INTEGER NOT NULL DEFAULT 0,
    output_path TEXT,
    thumbnail_path TEXT,
    youtube_video_id TEXT,
    instagram_media_id TEXT,
    instagram_url TEXT,
    facebook_video_id TEXT,
    facebook_url TEXT,
    error TEXT,
    PRIMARY KEY (job_id, clip_index),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_job_clips_job ON job_clips(job_id, clip_index);

CREATE TABLE IF NOT EXISTS channel_videos (
    channel_key TEXT NOT NULL,
    video_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    queued_at TEXT,
    job_id TEXT,
    PRIMARY KEY (channel_key, video_id)
);
"""

_MIGRATION_COLUMNS = {
    "instagram_caption": "TEXT",
    "instagram_media_id": "TEXT",
    "instagram_url": "TEXT",
    "facebook_video_id": "TEXT",
    "facebook_url": "TEXT",
    "archive_path": "TEXT",
}
_CLIP_MIGRATION_COLUMNS = {
    "thumbnail_path": "TEXT",
    "metadata_ready": "INTEGER NOT NULL DEFAULT 0",
    "enhancement_complete": "INTEGER NOT NULL DEFAULT 0",
    "facebook_video_id": "TEXT",
    "facebook_url": "TEXT",
    "youtube_uploaded_at": "TEXT",
    "instagram_uploaded_at": "TEXT",
    "facebook_uploaded_at": "TEXT",
}


class JobRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            existing = {
                row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            for name, column_type in _MIGRATION_COLUMNS.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {column_type}")

            existing_clip_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(job_clips)").fetchall()
            }
            for name, column_type in _CLIP_MIGRATION_COLUMNS.items():
                if name not in existing_clip_columns:
                    connection.execute(f"ALTER TABLE job_clips ADD COLUMN {name} {column_type}")

            # Meta can return Page Reel permalinks as paths such as /reel/123/. Normalize
            # previously stored values so manifests and progress output always contain links.
            connection.execute(
                """
                UPDATE jobs
                SET facebook_url = 'https://www.facebook.com' || facebook_url
                WHERE facebook_url LIKE '/%'
                """
            )
            connection.execute(
                """
                UPDATE job_clips
                SET facebook_url = 'https://www.facebook.com' || facebook_url
                WHERE facebook_url LIKE '/%'
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="microseconds")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            source_url=row["source_url"],
            status=JobStatus(row["status"]),
            progress_message=row["progress_message"],
            source_title=row["source_title"],
            short_title=row["short_title"],
            short_description=row["short_description"],
            instagram_caption=row["instagram_caption"],
            output_path=row["output_path"],
            youtube_video_id=row["youtube_video_id"],
            instagram_media_id=row["instagram_media_id"],
            instagram_url=row["instagram_url"],
            facebook_video_id=row["facebook_video_id"],
            facebook_url=row["facebook_url"],
            archive_path=row["archive_path"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _clip_from_row(row: sqlite3.Row) -> JobClip:
        return JobClip(
            job_id=row["job_id"],
            clip_index=row["clip_index"],
            start_seconds=row["start_seconds"],
            duration_seconds=row["duration_seconds"],
            title=row["title"],
            description=row["description"],
            instagram_caption=row["instagram_caption"],
            metadata_ready=bool(row["metadata_ready"]),
            enhancement_complete=bool(row["enhancement_complete"]),
            output_path=row["output_path"],
            thumbnail_path=row["thumbnail_path"],
            youtube_video_id=row["youtube_video_id"],
            instagram_media_id=row["instagram_media_id"],
            instagram_url=row["instagram_url"],
            facebook_video_id=row["facebook_video_id"],
            facebook_url=row["facebook_url"],
            error=row["error"],
        )

    def create(self, chat_id: int, user_id: int, source_url: str) -> Job:
        job_id = uuid.uuid4().hex[:12]
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, chat_id, user_id, source_url, status, progress_message,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    chat_id,
                    user_id,
                    source_url,
                    JobStatus.QUEUED.value,
                    "Waiting in queue",
                    now,
                    now,
                ),
            )
        job = self.get(job_id)
        assert job is not None
        return job

    def get(self, job_id: str) -> Job | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._from_row(row) if row else None

    def update(self, job_id: str, **fields: str | JobStatus | None) -> Job:
        allowed = {
            "status",
            "progress_message",
            "source_title",
            "short_title",
            "short_description",
            "instagram_caption",
            "output_path",
            "youtube_video_id",
            "instagram_media_id",
            "instagram_url",
            "facebook_video_id",
            "facebook_url",
            "archive_path",
            "error",
        }
        unknown = fields.keys() - allowed
        if unknown:
            raise ValueError(f"Unknown job fields: {', '.join(sorted(unknown))}")
        if "status" in fields and isinstance(fields["status"], JobStatus):
            fields["status"] = fields["status"].value
        fields["updated_at"] = self._now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [*fields.values(), job_id]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",  # noqa: S608
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown job {job_id}")
        job = self.get(job_id)
        assert job is not None
        return job

    def save_plans(
        self,
        job_id: str,
        plans: list[ShortPlan],
        metadata_ready: bool = True,
    ) -> list[JobClip]:
        with self._connect() as connection:
            for clip_index, plan in enumerate(plans, start=1):
                connection.execute(
                    """
                    INSERT INTO job_clips (
                        job_id, clip_index, start_seconds, duration_seconds,
                        title, description, instagram_caption, metadata_ready
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, clip_index) DO UPDATE SET
                        start_seconds = excluded.start_seconds,
                        duration_seconds = excluded.duration_seconds,
                        title = excluded.title,
                        description = excluded.description,
                        instagram_caption = excluded.instagram_caption,
                        metadata_ready = excluded.metadata_ready,
                        error = NULL
                    """,
                    (
                        job_id,
                        clip_index,
                        plan.start_seconds,
                        plan.duration_seconds,
                        plan.title,
                        plan.description,
                        plan.instagram_caption,
                        int(metadata_ready),
                    ),
                )
        return self.list_clips(job_id)

    def list_clips(self, job_id: str) -> list[JobClip]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_clips WHERE job_id = ? ORDER BY clip_index",
                (job_id,),
            ).fetchall()
        return [self._clip_from_row(row) for row in rows]

    def update_clip(self, job_id: str, clip_index: int, **fields: object) -> JobClip:
        allowed = {
            "start_seconds",
            "duration_seconds",
            "title",
            "description",
            "instagram_caption",
            "metadata_ready",
            "enhancement_complete",
            "output_path",
            "thumbnail_path",
            "youtube_video_id",
            "instagram_media_id",
            "instagram_url",
            "facebook_video_id",
            "facebook_url",
            "youtube_uploaded_at",
            "instagram_uploaded_at",
            "facebook_uploaded_at",
            "error",
        }
        unknown = fields.keys() - allowed
        if unknown:
            raise ValueError(f"Unknown clip fields: {', '.join(sorted(unknown))}")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [*fields.values(), job_id, clip_index]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE job_clips SET {assignments} WHERE job_id = ? AND clip_index = ?",  # noqa: S608
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown clip {job_id}/{clip_index}")
            row = connection.execute(
                "SELECT * FROM job_clips WHERE job_id = ? AND clip_index = ?",
                (job_id, clip_index),
            ).fetchone()
        assert row is not None
        return self._clip_from_row(row)

    def reset_clip_media(self, job_id: str) -> list[JobClip]:
        existing = self.list_clips(job_id)
        if not existing:
            return []
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE job_clips
                SET metadata_ready = 0, enhancement_complete = 0,
                    output_path = NULL, thumbnail_path = NULL,
                    youtube_video_id = NULL, instagram_media_id = NULL,
                    instagram_url = NULL, facebook_video_id = NULL,
                    facebook_url = NULL, error = NULL
                WHERE job_id = ?
                """,
                (job_id,),
            )
            connection.execute(
                """
                UPDATE jobs
                SET output_path = NULL, youtube_video_id = NULL,
                    instagram_media_id = NULL, instagram_url = NULL,
                    facebook_video_id = NULL, facebook_url = NULL,
                    archive_path = NULL, error = NULL
                WHERE id = ?
                """,
                (job_id,),
            )
        return existing

    def list_recent(self, user_id: int, limit: int = 10) -> list[Job]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_queued(self) -> list[Job]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at",
                (JobStatus.QUEUED.value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def pending_upload_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN output_path IS NOT NULL AND youtube_video_id IS NULL
                        THEN 1 ELSE 0 END) AS youtube,
                    SUM(CASE WHEN output_path IS NOT NULL AND instagram_media_id IS NULL
                        THEN 1 ELSE 0 END) AS instagram,
                    SUM(CASE WHEN output_path IS NOT NULL AND facebook_video_id IS NULL
                        THEN 1 ELSE 0 END) AS facebook
                FROM job_clips
                """
            ).fetchone()
        return {
            "YouTube": int(row["youtube"] or 0),
            "Instagram": int(row["instagram"] or 0),
            "Facebook": int(row["facebook"] or 0),
        }

    def list_pending_upload_jobs(
        self,
        *,
        youtube: bool,
        instagram: bool,
        facebook: bool,
        limit: int = 3,
    ) -> list[Job]:
        if not youtube and not instagram and not facebook:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT jobs.*
                FROM jobs
                JOIN job_clips ON job_clips.job_id = jobs.id
                WHERE job_clips.output_path IS NOT NULL
                  AND ((? = 1 AND job_clips.youtube_video_id IS NULL)
                    OR (? = 1 AND job_clips.instagram_media_id IS NULL)
                    OR (? = 1 AND job_clips.facebook_video_id IS NULL))
                  AND jobs.status IN (?, ?)
                ORDER BY jobs.updated_at ASC
                LIMIT ?
                """,
                (
                    int(youtube),
                    int(instagram),
                    int(facebook),
                    JobStatus.COMPLETE.value,
                    JobStatus.FAILED.value,
                    limit,
                ),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def clip_sequence_index(self, job_id: str, clip_index: int) -> int:
        with self._connect() as connection:
            current = connection.execute(
                "SELECT created_at FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if current is None:
                raise KeyError(f"Unknown job {job_id}")
            row = connection.execute(
                """
                SELECT COUNT(*) AS preceding
                FROM job_clips
                JOIN jobs ON jobs.id = job_clips.job_id
                WHERE jobs.created_at < ?
                   OR (jobs.created_at = ? AND jobs.id < ?)
                   OR (jobs.id = ? AND job_clips.clip_index < ?)
                """,
                (current["created_at"], current["created_at"], job_id, job_id, clip_index),
            ).fetchone()
        return int(row["preceding"])

    def filter_unseen_channel_videos(self, channel_key: str, video_ids: list[str]) -> set[str]:
        """Video IDs from the list that were never queued for this channel."""
        if not video_ids:
            return set()
        placeholders = ", ".join("?" for _ in video_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT video_id FROM channel_videos WHERE channel_key = ? "
                f"AND video_id IN ({placeholders})",
                (channel_key, *video_ids),
            ).fetchall()
        seen = {str(row["video_id"]) for row in rows}
        return {video_id for video_id in video_ids if video_id not in seen}

    def mark_channel_video_queued(
        self,
        channel_key: str,
        video_id: str,
        url: str,
        title: str,
        job_id: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO channel_videos (channel_key, video_id, url, title, queued_at, job_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (channel_key, video_id) DO UPDATE SET
                    queued_at = COALESCE(channel_videos.queued_at, excluded.queued_at),
                    job_id = COALESCE(channel_videos.job_id, excluded.job_id)
                """,
                (channel_key, video_id, url, title, self._now(), job_id),
            )

    def count_platform_uploads_since(self, platform: ChannelPlatform, since_iso: str) -> int:
        """How many clips were uploaded to a platform at/after an ISO timestamp (UTC)."""
        column = platform_uploaded_at_column(platform)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS uploads FROM job_clips WHERE {column} IS NOT NULL "
                f"AND {column} >= ?",
                (since_iso,),
            ).fetchone()
        return int(row["uploads"])

    def next_pending_clip(self, platform: ChannelPlatform) -> JobClip | None:
        """Oldest rendered clip that still lacks an upload to the given platform."""
        column = platform_column(platform)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT job_clips.*
                FROM job_clips
                JOIN jobs ON jobs.id = job_clips.job_id
                WHERE job_clips.{column} IS NULL
                  AND job_clips.output_path IS NOT NULL
                  AND job_clips.metadata_ready = 1
                  AND jobs.status != ?
                ORDER BY jobs.created_at, job_clips.job_id, job_clips.clip_index
                LIMIT 1
                """,
                (JobStatus.FAILED.value,),
            ).fetchone()
        return self._clip_from_row(row) if row else None

    def fail_interrupted(self) -> int:
        running = (
            JobStatus.DOWNLOADING,
            JobStatus.ANALYZING,
            JobStatus.RENDERING,
            JobStatus.UPLOADING,
        )
        placeholders = ",".join("?" for _ in running)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE jobs
                SET status = ?, progress_message = ?, error = ?, updated_at = ?
                WHERE status IN ({placeholders})
                """,  # noqa: S608
                (
                    JobStatus.FAILED.value,
                    "Stopped when the service restarted",
                    "The worker stopped before this job finished. Submit it again.",
                    self._now(),
                    *(status.value for status in running),
                ),
            )
            return cursor.rowcount
