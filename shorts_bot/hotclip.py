"""Bridge to HotClip, the external AI clipper (https://github.com/xixihhhh/hotclip).

HotClip (desktop or headless `pnpm cli clip`) is the content factory: it
transcribes, picks highlights, reframes to 9:16, burns word-synced dynamic
captions, and exports each clip with a cover JPG, a ``.post.txt`` publish
copy, and a ``clips.json`` receipt.

This module watches HotClip's export directory and turns every finished
clip into a queue entry the scheduler publishes. It only reads files —
HotClip stays a separate tool and is never modified.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv"}
_COVER_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
_HASHTAG_RE = re.compile(r"#[\w]+", re.UNICODE)
_TITLE_PREFIX_RE = re.compile(
    r"^(?:title|标题|hook|title card)\s*[:：-]\s*",
    re.IGNORECASE,
)
_BODY_PREFIX_RE = re.compile(
    r"^(?:description|desc|文案|caption|post)\s*[:：-]\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DiscoveredClip:
    mp4_path: Path
    cover_path: Path | None
    title: str
    description: str
    instagram_caption: str
    source_label: str


def _read_post_copy(mp4_path: Path) -> tuple[str, str, str]:
    """Parse ``<stem>.post.txt``: first line is the title, rest is body copy."""
    post_file = mp4_path.with_suffix(".post.txt")
    if not post_file.exists():
        # Some export layouts place copy next to the title inside the folder.
        return "", "", ""
    raw = post_file.read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return "", "", ""

    title = _TITLE_PREFIX_RE.sub("", lines[0]).strip() or mp4_path.stem
    hashtags: list[str] = []
    body_lines: list[str] = []
    for line in lines[1:]:
        body_lines.append(_BODY_PREFIX_RE.sub("", line))
        for tag in _HASHTAG_RE.findall(line):
            if tag not in hashtags:
                hashtags.append(tag)
    body = "\n".join(body_lines).strip()
    for tag in _HASHTAG_RE.findall(title):
        if tag not in hashtags:
            hashtags.append(tag)
    caption = " ".join([title, *hashtags]).strip()
    if hashtags:
        body = f"{body}\n\n{' '.join(hashtags)}".strip()
    return title, body, caption


def _locate_cover(mp4_path: Path) -> Path | None:
    for suffix in _COVER_SUFFIXES:
        candidate = mp4_path.with_suffix(suffix)
        if candidate.exists():
            return candidate
        candidate = mp4_path.with_name(f"{mp4_path.stem}-cover{suffix}")
        if candidate.exists():
            return candidate
    return None


def _clips_json_index(export_dir: Path) -> dict[str, dict]:
    """Best-effort ``basename -> entry`` index from the nearest clips.json files."""
    index: dict[str, dict] = {}
    for receipt in export_dir.rglob("clips.json"):
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = payload.get("clips", payload) if isinstance(payload, dict) else payload
        if isinstance(entries, dict):
            entries = list(entries.values())
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for key in ("file", "filename", "mp4", "clip", "output", "outputFile", "video"):
                value = entry.get(key)
                if isinstance(value, str) and value:
                    index[Path(value).name] = entry
                    break
    return index


def _apply_receipt(clip: DiscoveredClip, entry: dict) -> DiscoveredClip:
    """Enrich a discovered clip with fields from its clips.json entry."""
    def first_string(*keys: str) -> str:
        for key in keys:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    title = clip.title or first_string("title", "headline") or clip.mp4_path.stem
    description = clip.description or first_string("description", "post", "copy", "postCopy")
    caption = clip.instagram_caption or first_string("caption", "post", "copy") or title
    cover: Path | None = clip.cover_path
    if cover is None:
        for key in ("cover", "coverImage", "coverPath", "thumbnail"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                candidate = Path(value)
                if not candidate.is_absolute():
                    candidate = clip.mp4_path.parent / value
                if candidate.exists():
                    cover = candidate
                break
    source_label = clip.source_label or first_string(
        "source", "sourceTitle", "videoTitle", "input", "inputFile"
    )
    return DiscoveredClip(
        mp4_path=clip.mp4_path,
        cover_path=cover,
        title=title,
        description=description,
        instagram_caption=caption,
        source_label=source_label,
    )


def scan_export_dir(
    export_dir: Path,
    known_paths: set[str] | None = None,
    min_age_seconds: int = 90,
    now: float | None = None,
) -> list[DiscoveredClip]:
    """Find finished, previously unseen clips in HotClip's export directory.

    Files younger than ``min_age_seconds`` are skipped so a clip still being
    written by the renderer is never queued half-finished.
    """
    if not export_dir.is_dir():
        return []

    import time as time_module

    now = now if now is not None else time_module.time()
    known = known_paths or set()
    receipts = _clips_json_index(export_dir)
    discovered: list[DiscoveredClip] = []
    candidates = [
        path
        for suffix in _VIDEO_SUFFIXES
        for path in export_dir.rglob(f"*{suffix}")
        if path.is_file() and str(path) not in known
    ]
    for mp4_path in sorted(candidates, key=lambda path: (path.stat().st_mtime, path.name)):
        try:
            mtime = mp4_path.stat().st_mtime
        except OSError:
            continue
        if now - mtime < min_age_seconds:
            continue
        title, body, caption = _read_post_copy(mp4_path)
        cover = _locate_cover(mp4_path)
        clip = DiscoveredClip(
            mp4_path=mp4_path,
            cover_path=cover,
            title=title,
            description=body,
            instagram_caption=caption,
            source_label="",
        )
        receipt = receipts.get(mp4_path.name)
        if receipt is not None:
            clip = _apply_receipt(clip, receipt)
        if not clip.title:
            clip = DiscoveredClip(
                mp4_path=clip.mp4_path,
                cover_path=clip.cover_path,
                title=mp4_path.stem,
                description=clip.description,
                instagram_caption=clip.instagram_caption or mp4_path.stem,
                source_label=clip.source_label,
            )
        discovered.append(clip)
        receipts.pop(mp4_path.name, None)
    return discovered
