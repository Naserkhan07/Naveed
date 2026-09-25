from __future__ import annotations

import contextlib
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    ChannelPlatform,
    Event,
    Publication,
    platform_column,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_videos (
    channel_key TEXT NOT NULL,
    video_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    queued_at TEXT,
    PRIMARY KEY (channel_key, video_id)
);

CREATE TABLE IF NOT EXISTS publication_clips (
    id TEXT PRIMARY KEY,
    mp4_path TEXT NOT NULL UNIQUE,
    cover_path TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    instagram_caption TEXT NOT NULL DEFAULT '',
    source_label TEXT NOT NULL DEFAULT '',
    queued_at TEXT NOT NULL,
    youtube_video_id TEXT,
    youtube_uploaded_at TEXT,
    instagram_media_id TEXT,
    instagram_url TEXT,
    instagram_uploaded_at TEXT,
    facebook_video_id TEXT,
    facebook_url TEXT,
    facebook_uploaded_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_publication_queue ON publication_clips(queued_at, id);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_id ON events(id DESC);

CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_EVENT_KINDS = ("info", "system", "channel", "delivery", "queue", "publish", "error", "limit")
_EVENT_MAX_ROWS = 2_000


def _utc_now_seconds() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def heartbeat_timestamp() -> str:
    """UTC timestamp for watcher heartbeats (shared by watcher and panel tests)."""
    return _utc_now_seconds()

_PUBLICATION_COLUMNS = (
    "id",
    "mp4_path",
    "cover_path",
    "title",
    "description",
    "instagram_caption",
    "source_label",
    "queued_at",
    "youtube_video_id",
    "youtube_uploaded_at",
    "instagram_media_id",
    "instagram_url",
    "instagram_uploaded_at",
    "facebook_video_id",
    "facebook_url",
    "facebook_uploaded_at",
    "error",
)


class JobRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        if self.path.exists():
            with contextlib.suppress(sqlite3.OperationalError):
                connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="microseconds")

    # ---- channel discovery memory -------------------------------------------------

    def filter_unseen_channel_videos(self, channel_key: str, video_ids: list[str]) -> set[str]:
        """Video IDs from the list that were never handed to HotClip for this channel."""
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
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO channel_videos (channel_key, video_id, url, title, queued_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (channel_key, video_id) DO UPDATE SET
                    queued_at = COALESCE(channel_videos.queued_at, excluded.queued_at),
                    title = excluded.title
                """,
                (channel_key, video_id, url, title, self._now()),
            )

    # ---- publication queue ---------------------------------------------------------

    def publication_exists(self, mp4_path: Path) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM publication_clips WHERE mp4_path = ?",
                (str(mp4_path),),
            ).fetchone()
        return row is not None

    def add_publication(
        self,
        mp4_path: Path,
        title: str,
        description: str = "",
        instagram_caption: str = "",
        cover_path: Path | None = None,
        source_label: str = "",
    ) -> Publication:
        publication_id = uuid.uuid4().hex[:12]
        if not description:
            description = title
        if not instagram_caption:
            instagram_caption = title
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO publication_clips (
                    id, mp4_path, cover_path, title, description, instagram_caption,
                    source_label, queued_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    publication_id,
                    str(mp4_path),
                    str(cover_path) if cover_path else None,
                    title,
                    description,
                    instagram_caption,
                    source_label,
                    self._now(),
                ),
            )
        publication = self.get_publication(publication_id)
        assert publication is not None
        return publication

    def get_publication(self, publication_id: str) -> Publication | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM publication_clips WHERE id = ?",
                (publication_id,),
            ).fetchone()
        return self._publication_from_row(row) if row else None

    def list_publications(self, limit: int = 500) -> list[Publication]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM publication_clips ORDER BY queued_at, id LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._publication_from_row(row) for row in rows]

    def update_publication(self, publication_id: str, **fields: object) -> Publication:
        if not fields:
            publication = self.get_publication(publication_id)
            if publication is None:
                raise KeyError(f"Unknown publication {publication_id}")
            return publication
        allowed = set(_PUBLICATION_COLUMNS) - {"id"}
        unknown = fields.keys() - allowed
        if unknown:
            raise ValueError(f"Unknown publication fields: {', '.join(sorted(unknown))}")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [*fields.values(), publication_id]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE publication_clips SET {assignments} WHERE id = ?",  # noqa: S608
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown publication {publication_id}")
        publication = self.get_publication(publication_id)
        assert publication is not None
        return publication

    def next_pending_publication(self, platform: ChannelPlatform) -> Publication | None:
        """Oldest queued clip still missing an upload to the platform, file present."""
        column = platform_column(platform)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM publication_clips
                WHERE {column} IS NULL
                ORDER BY queued_at, id
                LIMIT 1
                """,
            ).fetchone()
        return self._publication_from_row(row) if row else None

    def count_platform_uploads_since(self, platform: ChannelPlatform, since_iso: str) -> int:
        column = f"{platform.value.lower()}_uploaded_at"
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS uploads FROM publication_clips "
                f"WHERE {column} IS NOT NULL AND {column} >= ?",
                (since_iso,),
            ).fetchone()
        return int(row["uploads"])

    def pending_publication_counts(self) -> dict[str, int]:
        counts = {"YouTube": 0, "Instagram": 0, "Facebook": 0}
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN youtube_video_id IS NULL THEN 1 ELSE 0 END) AS youtube,
                    SUM(CASE WHEN instagram_media_id IS NULL THEN 1 ELSE 0 END) AS instagram,
                    SUM(CASE WHEN facebook_video_id IS NULL THEN 1 ELSE 0 END) AS facebook
                FROM publication_clips
                """,
            ).fetchone()
        if rows:
            counts["YouTube"] = int(rows["youtube"] or 0)
            counts["Instagram"] = int(rows["instagram"] or 0)
            counts["Facebook"] = int(rows["facebook"] or 0)
        return counts

    # ---- activity feed + watcher state (status panel) ------------------------------

    def log_event(self, kind: str, message: str) -> None:
        """Append one activity-feed entry (e.g. what was published, when, where)."""
        if kind not in _EVENT_KINDS:
            kind = "info"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO events (ts, kind, message) VALUES (?, ?, ?)",
                (self._now(), kind, message[:600]),
            )
            # Keep the feed bounded: drop the oldest half once it doubles the cap.
            count = connection.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            if count > 2 * _EVENT_MAX_ROWS:
                connection.execute(
                    "DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id LIMIT ?)",
                    (count - _EVENT_MAX_ROWS,),
                )

    def recent_events(self, limit: int = 150) -> list[Event]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT ts, kind, message FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Event(ts=str(row["ts"]), kind=str(row["kind"]), message=str(row["message"]))
            for row in rows
        ]

    def set_state(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO bot_state (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_state(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM bot_state WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else None

    def platform_summary(self, platform: ChannelPlatform) -> dict[str, object]:
        """pending/done totals plus the most recent upload timestamp for one platform."""
        id_column = platform_column(platform)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total, COUNT({id_column}) AS done, "  # noqa: S608
                f"MAX({platform.value.lower()}_uploaded_at) AS last_at "
                f"FROM publication_clips"
            ).fetchone()
        total = int(row["total"])
        done = int(row["done"])
        return {"total": total, "done": done, "pending": total - done, "last_at": row["last_at"]}

    @staticmethod
    def _publication_from_row(row: sqlite3.Row) -> Publication:
        return Publication(**{name: row[name] for name in _PUBLICATION_COLUMNS})


logger = logging.getLogger(__name__)


def log_safely(repository: JobRepository, kind: str, message: str) -> None:
    """Write an activity-feed event without ever breaking the caller's work."""
    try:
        repository.log_event(kind, message)
    except Exception:  # noqa: BLE001
        logger.warning("Could not write status event: %s", message, exc_info=True)


def state_safely(repository: JobRepository, key: str, value: str) -> None:
    """Write a bot_state heartbeat without ever breaking the caller's work."""
    try:
        repository.set_state(key, value)
    except Exception:  # noqa: BLE001
        logger.warning("Could not write bot state %s", key, exc_info=True)
