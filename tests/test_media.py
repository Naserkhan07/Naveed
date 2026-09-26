from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shorts_bot.media import MediaError, MediaProcessor


def test_check_tools_reports_missing_ffprobe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shorts_bot.media.shutil.which", lambda tool: None)
    processor = MediaProcessor()
    with pytest.raises(Exception, match="ffprobe"):
        processor.check_tools()


def test_probe_duration_parses_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        return subprocess.CompletedProcess(
            command, 0, stdout='{"format": {"duration": "29.98"}}', stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    processor = MediaProcessor()
    assert processor.probe_duration(tmp_path / "clip.mp4") == pytest.approx(29.98)


def test_probe_duration_invalid_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        return subprocess.CompletedProcess(command, 0, stdout="not-json", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    processor = MediaProcessor()
    with pytest.raises(MediaError):
        processor.probe_duration(tmp_path / "clip.mp4")
