from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .errors import ConfigurationError, MediaError


class MediaProcessor:
    """Lightweight FFprobe helpers (clipping/rendering is HotClip's job now)."""

    def __init__(self, ffprobe: str = "ffprobe") -> None:
        self.ffprobe = ffprobe

    def check_tools(self) -> None:
        if shutil.which(self.ffprobe) is None:
            raise ConfigurationError(
                f"Required media tool not found in PATH: {self.ffprobe}. "
                "Install FFmpeg (its ffprobe binary) and restart."
            )

    def probe_duration(self, path: Path) -> float:
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            raise MediaError(f"Could not probe {path}: {exc.stderr.strip()[-400:]}") from exc
        try:
            duration = float(json.loads(completed.stdout)["format"]["duration"])
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise MediaError(f"Could not read the duration of {path}.") from exc
        return duration
