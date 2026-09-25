"""Live localhost status panel for the autopilot.

Whenever the watcher (``main.py``) runs, this module serves a small dashboard
(default: http://localhost:8000) showing exactly what the bot has done and is
about to do:

* a RUNNING/STALE badge driven by the watcher's database heartbeat,
* per-platform progress: uploads done today vs owed, slot credits due, the
  queue backlog, last/next scheduled slot, total published,
* an activity feed answering "what, when, where" — every discovery, HotClip
  delivery, queued clip, publish (with links), limit, and error,
* the publication queue with per-platform status and direct links.

It uses only the standard library (no new dependencies) and can also run
standalone, read-only against the same database:

    python -m shorts_bot.status_panel
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time as time_module
from datetime import UTC, datetime, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings
from .db import JobRepository
from .downloader import is_youtube_url
from .hashtags import load_hashtags
from .models import ChannelPlatform, Publication
from .scheduler import (
    PlatformSchedule,
    due_credits,
    now_in,
    platform_schedules,
    schedule_timezone,
)

logger = logging.getLogger(__name__)

_HEARTBEAT_STALE_SECONDS = 120  # default; STATUS_STALE_AFTER_SECONDS overrides
_WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_QUEUE_LIMIT = 25
_EVENT_LIMIT = 120


# ---------------------------------------------------------------------------
# Status assembly
# ---------------------------------------------------------------------------


def _settings_schedules(settings: Settings) -> dict[ChannelPlatform, PlatformSchedule]:
    return platform_schedules(
        (settings.youtube_schedule_times, settings.youtube_uploads_per_slot),
        (settings.instagram_schedule_times, settings.instagram_uploads_per_slot),
        (settings.facebook_schedule_times, settings.facebook_uploads_per_slot),
    )


def _platform_enabled(settings: Settings, platform: ChannelPlatform) -> bool:
    return bool(getattr(settings, f"upload_{platform.value.lower()}"))


def _slot_states(
    schedule: PlatformSchedule,
    weekday: int,
    moment: time,
    uploads_today: int,
) -> list[dict[str, object]]:
    slots: list[dict[str, object]] = []
    for index, slot in enumerate(schedule.slots_today(weekday)):
        if slot > moment:
            state, filled = "upcoming", 0
        else:
            filled = min(
                schedule.uploads_per_slot,
                max(0, uploads_today - index * schedule.uploads_per_slot),
            )
            if filled >= schedule.uploads_per_slot:
                state = "done"
            elif filled > 0:
                state = "partial"
            else:
                state = "due"
        slots.append(
            {
                "time": slot.strftime("%H:%M"),
                "state": state,
                "done": filled,
                "cap": schedule.uploads_per_slot,
            }
        )
    return slots


def _next_slot_label(schedule: PlatformSchedule, weekday: int, moment: time) -> str:
    for slot in schedule.slots_today(weekday):
        if slot > moment:
            return f"today {slot.strftime('%H:%M')}"
    for days_ahead in range(1, 8):
        day = (weekday + days_ahead) % 7
        times = schedule.per_day.get(day, [])
        if times:
            prefix = "tomorrow" if days_ahead == 1 else _WEEKDAY_NAMES[day]
            return f"{prefix} {times[0].strftime('%H:%M')}"
    return "never"


def _queue_rows(repository: JobRepository, settings: Settings) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for publication in repository.list_publications(_QUEUE_LIMIT):
        cells: dict[str, dict[str, object]] = {}
        for platform in ChannelPlatform:
            platforms_id = publication.platform_id(platform)
            url = ""
            if platform is ChannelPlatform.YOUTUBE and platforms_id:
                url = f"https://youtu.be/{platforms_id}"
            elif platform is ChannelPlatform.INSTAGRAM:
                url = publication.instagram_url or ""
            elif platform is ChannelPlatform.FACEBOOK:
                url = publication.facebook_url or ""
            cells[platform.value] = {
                "enabled": _platform_enabled(settings, platform),
                "done": bool(platforms_id),
                "url": url if platforms_id else "",
                "at": _uploaded_at(publication, platform),
            }
        rows.append(
            {
                "title": publication.title,
                "queued_at": publication.queued_at,
                "source": publication.source_label,
                "error": publication.error or "",
                "platforms": cells,
            }
        )
    return rows


def _uploaded_at(publication: Publication, platform: ChannelPlatform) -> str:
    if platform is ChannelPlatform.YOUTUBE:
        return publication.youtube_uploaded_at or ""
    if platform is ChannelPlatform.INSTAGRAM:
        return publication.instagram_uploaded_at or ""
    return publication.facebook_uploaded_at or ""


def _count_config_lines(path: Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    return sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))


def _count_pending_links(path: Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    urls = {
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#") and is_youtube_url(line.strip())
    }
    return len(urls)


def build_status(settings: Settings, repository: JobRepository) -> dict[str, object]:
    """Assemble the complete panel snapshot shown to the browser and API."""
    timezone = schedule_timezone(settings.schedule_timezone)
    local_now = now_in(timezone)
    moment = local_now.time().replace(tzinfo=None)
    weekday = local_now.weekday()
    utc_now = datetime.now(UTC)
    start_of_today_utc = (
        local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
        .isoformat(timespec="seconds")
    )

    heartbeat_raw = repository.get_state("heartbeat")
    heartbeat_age: float | None = None
    if heartbeat_raw:
        try:
            heartbeat_age = max(
                0.0, (utc_now - datetime.fromisoformat(heartbeat_raw)).total_seconds()
            )
        except ValueError:
            heartbeat_age = None
    stale_after = max(
        settings.status_stale_after_seconds,
        _HEARTBEAT_STALE_SECONDS,
        3 * settings.links_poll_seconds,
    )
    running = heartbeat_age is not None and heartbeat_age <= stale_after

    schedules = _settings_schedules(settings)
    platforms: list[dict[str, object]] = []
    for platform in ChannelPlatform:
        schedule = schedules.get(platform)
        summary = repository.platform_summary(platform)
        uploads_today = repository.count_platform_uploads_since(platform, start_of_today_utc)
        entry: dict[str, object] = {
            "name": platform.value,
            "enabled": _platform_enabled(settings, platform),
            "scheduled": schedule is not None,
            "uploads_today": uploads_today,
            "total_done": summary["done"],
            "queue_pending": summary["pending"],
            "last_upload_at": summary["last_at"] or "",
        }
        if schedule is not None:
            owed = schedule.uploads_owed_until(weekday, moment)
            entry.update(
                {
                    "owed_now": owed,
                    "credits_due": due_credits(schedule, uploads_today, local_now),
                    "uploads_per_slot": schedule.uploads_per_slot,
                    "slots": _slot_states(schedule, weekday, moment, uploads_today),
                    "slots_today_count": len(schedule.slots_today(weekday)),
                    "next_slot": _next_slot_label(schedule, weekday, moment),
                }
            )
        else:
            entry.update({"owed_now": uploads_today, "credits_due": 0, "next_slot": "no schedule"})
        platforms.append(entry)

    hashtag_count = len(load_hashtags(settings.hashtags_file)) if settings.hashtags_enabled else 0
    return {
        "generated_at": utc_now.isoformat(timespec="seconds"),
        "local_time": local_now.strftime("%H:%M:%S"),
        "timezone": str(timezone),
        "watcher": {
            "running": running,
            "heartbeat_at": heartbeat_raw or "",
            "started_at": repository.get_state("started_at") or "",
            "stale_after_seconds": stale_after,
        },
        "platforms": platforms,
        "events": [
            {"ts": event.ts, "kind": event.kind, "message": event.message}
            for event in repository.recent_events(_EVENT_LIMIT)
        ],
        "queue": _queue_rows(repository, settings),
        "config": {
            "hotclip_watch_dir": str(settings.hotclip_watch_dir),
            "hotclip_export_dir": str(settings.hotclip_export_dir),
            "hashtags_enabled": settings.hashtags_enabled,
            "hashtag_count": hashtag_count,
            "hashtag_file": str(settings.hashtags_file),
            "channels": _count_config_lines(settings.channels_file),
            "links_pending": _count_pending_links(settings.links_file),
            "scan_interval_minutes": settings.channel_scan_interval_minutes,
            "delete_uploaded_clips": settings.delete_uploaded_clips,
        },
    }


# ---------------------------------------------------------------------------
# Dashboard page
# ---------------------------------------------------------------------------

_INDEX_HTML = files("shorts_bot").joinpath("status_page.html").read_text(
    encoding="utf-8"
)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class _StatusHandler(BaseHTTPRequestHandler):
    panel: StatusPanel  # injected by _make_handler

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        route = urlparse(self.path).path
        try:
            if route in ("/", "/index.html"):
                self._respond("text/html; charset=utf-8", _INDEX_HTML.encode("utf-8"))
            elif route in ("/api/status", "/api/status.json"):
                # The .json alias lets the same page work both live (localhost)
                # and as a static GitHub Pages export.
                payload = json.dumps(build_status(self.panel.settings, self.panel.repository))
                self._respond("application/json; charset=utf-8", payload.encode("utf-8"))
            elif route == "/healthz":
                self._respond("text/plain; charset=utf-8", b"ok")
            else:
                self.send_error(404, "Not found")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Status panel request failed: %s", exc, exc_info=True)
            with contextlib.suppress(OSError):
                self._respond(
                    "application/json; charset=utf-8",
                    json.dumps({"error": str(exc)}).encode("utf-8"),
                    status=500,
                )

    def _respond(self, content_type: str, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.debug("status-panel http: " + format, *args)


def _make_handler(panel: StatusPanel) -> type[_StatusHandler]:
    return type("_BoundStatusHandler", (_StatusHandler,), {"panel": panel})


class StatusPanel:
    """Background ThreadingHTTPServer serving the dashboard until stopped."""

    def __init__(self, settings: Settings, repository: JobRepository, host: str, port: int) -> None:
        self.settings = settings
        self.repository = repository
        self.host = host
        self.port = port
        self.url = ""
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Bind the first free port (the chosen one shows up in ``self.url``)."""
        last_error: OSError | None = None
        for offset in range(10):
            candidate = self.port + offset
            if candidate > 65_535:
                break
            try:
                server = ThreadingHTTPServer((self.host, candidate), _make_handler(self))
            except OSError as exc:
                last_error = exc
                continue
            self._server = server
            break
        if self._server is None:
            raise last_error or OSError("no free port for the status panel")
        actual_port = self._server.server_address[1]
        self.port = actual_port
        display_host = self.host if self.host not in ("0.0.0.0", "") else "localhost"
        self.url = f"http://{display_host}:{actual_port}/"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.5},
            name="status-panel",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


def start_status_panel(settings: Settings, repository: JobRepository) -> StatusPanel | None:
    """Start the panel if enabled; failures never stop the watcher."""
    if not settings.status_panel_enabled:
        logger.info("Status panel disabled (STATUS_PANEL_ENABLED=false).")
        return None
    panel = StatusPanel(
        settings, repository, settings.status_panel_host, settings.status_panel_port
    )
    try:
        panel.start()
    except OSError as exc:
        logger.warning(
            "Status panel could not start (%s); the watcher continues without it.", exc
        )
        return None
    return panel


def main() -> None:
    """Standalone read-only panel: python -m shorts_bot.status_panel"""
    from dotenv import load_dotenv

    load_dotenv()
    settings = Settings.from_env()
    repository = JobRepository(settings.database_path)
    panel = StatusPanel(
        settings, repository, settings.status_panel_host, settings.status_panel_port
    )
    try:
        panel.start()
    except OSError as exc:
        raise SystemExit(f"Could not start the status panel: {exc}") from exc
    print(
        f"Status panel live at {panel.url} — leave this running to watch the bot. Ctrl+C to stop.",
        flush=True,
    )
    try:
        while True:
            time_module.sleep(3600)
    except KeyboardInterrupt:
        print("\nStatus panel stopped.")
    finally:
        panel.stop()


if __name__ == "__main__":
    main()
