from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shorts_bot.config import Settings
from shorts_bot.db import JobRepository, heartbeat_timestamp
from shorts_bot.models import ChannelPlatform
from shorts_bot.pages_export import export_pages_site
from shorts_bot.status_panel import StatusPanel, build_status

_PANEL_ENV = (
    "STATUS_PANEL_ENABLED",
    "STATUS_PANEL_HOST",
    "STATUS_PANEL_PORT",
    "STATUS_STALE_AFTER_SECONDS",
)


@pytest.fixture(autouse=True)
def _clean_panel_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PANEL_ENV:
        monkeypatch.delenv(name, raising=False)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base = Settings.from_env(env_file=None)
    return replace(
        base,
        schedule_timezone="UTC",
        youtube_schedule_times="00:00",  # slot always already passed today
        youtube_uploads_per_slot=2,
        instagram_schedule_times="00:00",
        instagram_uploads_per_slot=2,
        facebook_schedule_times="00:00",
        facebook_uploads_per_slot=2,
        work_dir=tmp_path / "work",
        database_path=tmp_path / "work" / "jobs.db",
        hotclip_watch_dir=tmp_path / "watch",
        hotclip_export_dir=tmp_path / "exports",
        links_file=tmp_path / "links.txt",
        downloaded_links_log=tmp_path / "work" / "downloaded-links.log",
        channels_file=tmp_path / "channels.txt",
        hashtags_file=tmp_path / "hashtags.txt",
        status_panel_host="127.0.0.1",
        status_panel_port=0,  # test mode: any free port
        **overrides,  # type: ignore[arg-type]
    )


def _seed_repository(tmp_path: Path, settings: Settings) -> JobRepository:
    repository = JobRepository(settings.database_path)
    clip = tmp_path / "exports" / "clip-a.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip")
    publication = repository.add_publication(clip, title="Clip A", description="body")
    repository.update_publication(
        publication.id,
        youtube_video_id="abc123",
        youtube_uploaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    repository.log_event("publish", "Published to YouTube: Clip A — https://youtu.be/abc123")
    repository.log_event("system", "Watcher started — status panel at http://localhost:8000/")
    return repository


def _platform(status: dict[str, object], name: str) -> dict[str, object]:
    for entry in status["platforms"]:  # type: ignore[union-attr]
        if entry["name"] == name:  # type: ignore[index]
            return entry  # type: ignore[return-value]
    raise AssertionError(f"platform {name} missing")


def test_build_status_reports_running_heartbeat_and_progress(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = _seed_repository(tmp_path, settings)
    repository.set_state("heartbeat", heartbeat_timestamp())
    repository.set_state("started_at", heartbeat_timestamp())

    status = build_status(settings, repository)

    assert status["watcher"]["running"] is True  # type: ignore[index]
    assert status["config"]["ready_clip_count"] == 1  # type: ignore[index]
    assert status["config"]["ready_buffer_target"] == settings.ready_clip_buffer_target  # type: ignore[index]
    youtube = _platform(status, "YouTube")
    assert youtube["uploads_today"] == 1
    assert youtube["owed_now"] == 2
    assert youtube["credits_due"] == 1
    assert youtube["total_done"] == 1
    assert youtube["queue_pending"] == 0
    instagram = _platform(status, "Instagram")
    assert instagram["uploads_today"] == 0
    assert instagram["credits_due"] == 2
    assert instagram["queue_pending"] == 1

    events = status["events"]
    assert events and events[0]["message"].startswith("Watcher started")  # newest first
    assert any("Published to YouTube: Clip A" in e["message"] for e in events)

    (row,) = status["queue"]
    assert row["title"] == "Clip A"
    assert row["platforms"]["YouTube"]["done"] is True
    assert row["platforms"]["YouTube"]["url"] == "https://youtu.be/abc123"
    assert row["platforms"]["Facebook"]["done"] is False


def test_build_status_marks_stale_watcher(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = JobRepository(settings.database_path)
    status = build_status(settings, repository)
    assert status["watcher"]["running"] is False  # type: ignore[index]


def test_platform_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings.from_env(env_file=None)
    assert settings.status_panel_enabled is True
    assert settings.status_panel_host == "127.0.0.1"
    assert settings.status_panel_port == 8000
    assert settings.status_stale_after_seconds == 120


def test_stale_threshold_respects_cloud_runs(tmp_path: Path) -> None:
    old_heartbeat = (datetime.now(UTC) - timedelta(minutes=30)).isoformat(timespec="seconds")

    settings = _settings(tmp_path)
    repository = JobRepository(settings.database_path)
    repository.set_state("heartbeat", old_heartbeat)
    assert build_status(settings, repository)["watcher"]["running"] is False  # type: ignore[index]

    cloud = _settings(tmp_path, status_stale_after_seconds=2700)
    assert build_status(cloud, repository)["watcher"]["running"] is True  # type: ignore[index]


def test_pages_export_writes_static_dashboard(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = _seed_repository(tmp_path, settings)
    repository.set_state("heartbeat", heartbeat_timestamp())

    index = export_pages_site(settings, repository, tmp_path / "site")

    assert index.name == "index.html"
    assert "Shorts Autopilot" in index.read_text(encoding="utf-8")
    assert "Ready before the next slot" in index.read_text(encoding="utf-8")
    payload = json.loads(
        (tmp_path / "site" / "api" / "status.json").read_text(encoding="utf-8")
    )
    assert payload["queue"][0]["title"] == "Clip A"
    assert payload["watcher"]["running"] is True
    assert [platform["name"] for platform in payload["platforms"]] == [
        "YouTube",
        "Instagram",
        "Facebook",
    ]


def _http_get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_http_server_serves_dashboard_json_and_health(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = _seed_repository(tmp_path, settings)
    repository.set_state("heartbeat", heartbeat_timestamp())

    panel = StatusPanel(settings, repository, "127.0.0.1", 0)
    panel.start()
    try:
        base = f"http://127.0.0.1:{panel.port}"
        assert panel.url.endswith(f":{panel.port}/")

        status, body = _http_get(f"{base}/")
        assert status == 200
        assert b"Shorts Autopilot" in body
        assert b"/api/status" in body

        status, body = _http_get(f"{base}/api/status")
        assert status == 200
        payload = json.loads(body)
        alias_status, alias_body = _http_get(f"{base}/api/status.json")
        assert alias_status == 200
        assert json.loads(alias_body)["platforms"]
        assert {entry["name"] for entry in payload["platforms"]} == {
            "YouTube",
            "Instagram",
            "Facebook",
        }
        assert payload["watcher"]["running"] is True
        assert payload["queue"][0]["title"] == "Clip A"
        assert payload["timezone"] == "UTC"

        status, body = _http_get(f"{base}/healthz")
        assert (status, body) == (200, b"ok")

        status, _ = _http_get(f"{base}/does-not-exist")
        assert status == 404
    finally:
        panel.stop()


def test_channel_platform_enum_still_covers_three_platforms() -> None:
    assert [platform.value for platform in ChannelPlatform] == [
        "YouTube",
        "Instagram",
        "Facebook",
    ]
