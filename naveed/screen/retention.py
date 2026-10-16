"""Bounded on-disk storage for screen captures.

Ported from **brah** (https://github.com/KenKaiii/brah, MIT) —
``src/realtime/tools/screenshot-retention.js`` and
``src/realtime/tools/screenshot-list.js``.

Why this matters for a bot that "sits and watches your screen": the watcher can
easily write a frame every couple of seconds, which would quietly eat gigabytes
and slow the machine it is supposed to help.  The original caps retention at 100
captures, never deletes the capture the agent is currently using, sorts by
modification time, and tolerates stat/delete races.  All of that is preserved.

Changes from the original
-------------------------
* ``ScreenshotStore`` bundles naming, saving, pruning and listing so the watcher
  only talks to one object.
* Names still match the original's regex exactly
  (``screenshot-<utc>Z[-<uuid>].png``) so pruning recognises older captures.
* Listing returns ``data_url`` strings for the panel's capture gallery, as the
  original did for the renderer.
"""

from __future__ import annotations

import base64
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

__all__ = [
    "CAPTURE_NAME_RE",
    "DEFAULT_MAX_CAPTURES",
    "MAX_LISTED_CAPTURES",
    "ScreenshotStore",
    "capture_filename",
    "list_saved_screenshots",
    "prune_saved_screenshots",
]

#: Byte-for-byte compatibility with brah's captureName regex.
CAPTURE_NAME_RE = re.compile(
    r"^screenshot-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z"
    r"(?:-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})?\.png$"
)

DEFAULT_MAX_CAPTURES = 100
MAX_LISTED_CAPTURES = 30


def capture_filename(when: Optional[datetime] = None, *, unique: bool = True) -> str:
    """Build a capture name that :data:`CAPTURE_NAME_RE` accepts."""
    when = when or datetime.now(timezone.utc)
    stamp = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-") + f"{when.microsecond // 1000:03d}Z"
    suffix = f"-{uuid.uuid4()}" if unique else ""
    return f"screenshot-{stamp}{suffix}.png"


def prune_saved_screenshots(
    screenshots_dir: str,
    *,
    max_captures: int = DEFAULT_MAX_CAPTURES,
    protected_name: Optional[str] = None,
    file_system: Any = None,
) -> Dict[str, int]:
    """Delete the oldest captures beyond *max_captures*.

    ``protected_name`` is the capture the agent is actively using and is ranked
    first, so it survives the sweep even when it is the oldest file.
    """
    fs = file_system or os
    try:
        names = [name for name in fs.listdir(screenshots_dir) if CAPTURE_NAME_RE.match(name)]
    except FileNotFoundError:
        return {"found": 0, "deleted": 0}

    captures: List[Dict[str, Any]] = []
    for name in names:
        try:
            path = os.path.join(screenshots_dir, name)
            stats = fs.stat(path) if file_system else os.stat(path)
        except FileNotFoundError:
            continue
        except OSError:
            continue
        captures.append({"name": name, "modified_at": getattr(stats, "st_mtime", 0.0)})

    captures.sort(
        key=lambda entry: (
            entry["name"] == protected_name,
            entry["modified_at"],
            entry["name"],
        ),
        reverse=True,
    )

    deleted = 0
    for entry in captures[max_captures:]:
        try:
            os.unlink(os.path.join(screenshots_dir, entry["name"]))
            deleted += 1
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return {"found": len(captures), "deleted": deleted}


def list_saved_screenshots(
    screenshots_dir: str,
    *,
    limit: int = MAX_LISTED_CAPTURES,
    with_data_url: bool = True,
) -> List[Dict[str, Any]]:
    """Newest-first capture listing, optionally with base64 PNG payloads."""
    try:
        names = [name for name in os.listdir(screenshots_dir) if name.lower().endswith(".png")]
    except FileNotFoundError:
        return []

    candidates: List[Dict[str, Any]] = []
    for name in names:
        path = os.path.join(screenshots_dir, name)
        try:
            stats = os.stat(path)
        except OSError:
            continue
        if not os.path.isfile(path):
            continue
        candidates.append({"name": name, "created_at": stats.st_mtime, "path": path})

    candidates.sort(key=lambda entry: (entry["created_at"], entry["name"]), reverse=True)
    entries: List[Dict[str, Any]] = []
    for entry in candidates[:limit]:
        record = {"name": entry["name"], "created_at": entry["created_at"], "path": entry["path"]}
        if with_data_url:
            try:
                with open(entry["path"], "rb") as handle:
                    record["data_url"] = "data:image/png;base64," + base64.b64encode(handle.read()).decode("ascii")
            except OSError:
                record["data_url"] = ""
        entries.append(record)
    return entries


@dataclass
class ScreenshotStore:
    """Folder-backed capture store with automatic pruning."""

    directory: str
    max_captures: int = DEFAULT_MAX_CAPTURES
    prune_every: int = 12

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._writes = 0
        self._since_prune = 0
        # Estimated number of captures on disk.  Starting from the real count
        # means a folder that already has files in it is cleaned up on the next
        # write instead of after ``max_captures`` more of them.
        self._count_estimate = self._count_existing()
        self._protected: Optional[str] = None
        os.makedirs(self.directory, exist_ok=True)

    def _count_existing(self) -> int:
        try:
            return sum(1 for name in os.listdir(self.directory) if CAPTURE_NAME_RE.match(name))
        except OSError:
            return 0

    # --- writing ------------------------------------------------------
    def new_path(self, *, unique: bool = True) -> str:
        return os.path.join(self.directory, capture_filename(unique=unique))

    def save_bytes(self, png_bytes: bytes, *, name: Optional[str] = None, protect: bool = False) -> str:
        """Write a capture and return its path.

        Pruning runs as soon as the folder would exceed ``max_captures``, and at
        worst every ``prune_every`` writes as a backstop, so the screenshots
        folder cannot grow without bound even during a long unattended session.
        """
        target = os.path.join(self.directory, name) if name else self.new_path()
        with self._lock:
            with open(target, "wb") as handle:
                handle.write(png_bytes)
            if protect:
                self._protected = os.path.basename(target)
            self._writes += 1
            self._since_prune += 1
            self._count_estimate += 1
            should_prune = self._count_estimate > self.max_captures or (
                self.prune_every > 0 and self._since_prune >= self.prune_every
            )
        if should_prune:
            self.prune()
        return target

    def save_image(self, image: Any, *, protect: bool = False) -> str:
        """Save a PIL image (kept in PNG to match the original's contract)."""
        buffer = image if isinstance(image, (bytes, bytearray)) else None
        if buffer is None:
            buffer = _png_bytes(image)
        return self.save_bytes(bytes(buffer), protect=protect)

    # --- maintenance --------------------------------------------------
    def prune(self) -> Dict[str, int]:
        result = prune_saved_screenshots(
            self.directory,
            max_captures=self.max_captures,
            protected_name=self._protected,
        )
        with self._lock:
            self._since_prune = 0
            # Trust the sweep's own count rather than our estimate.
            self._count_estimate = max(0, int(result.get("found", 0)) - int(result.get("deleted", 0)))
        return result

    def recent(self, limit: int = MAX_LISTED_CAPTURES, *, with_data_url: bool = True) -> List[Dict[str, Any]]:
        return list_saved_screenshots(self.directory, limit=limit, with_data_url=with_data_url)

    def protect(self, path: Optional[str]) -> None:
        self._protected = os.path.basename(path) if path else None

    def stats(self) -> Dict[str, Any]:
        captures = [name for name in os.listdir(self.directory) if CAPTURE_NAME_RE.match(name)] if os.path.isdir(self.directory) else []
        total = 0
        for name in captures:
            try:
                total += os.path.getsize(os.path.join(self.directory, name))
            except OSError:
                continue
        return {"count": len(captures), "bytes": total, "max_captures": self.max_captures}


def _png_bytes(image: Any) -> bytes:
    """Encode a PIL image to PNG bytes, importing PIL lazily."""
    from .. import lazy

    lazy.load("PIL.Image", extra="capture")
    import io

    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()
