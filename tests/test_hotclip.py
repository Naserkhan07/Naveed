from __future__ import annotations

import json
import os
import time
from pathlib import Path  # noqa: F401  (kept for type clarity in helpers)

from shorts_bot.hotclip import scan_export_dir


def _write_clip(path: Path, age_seconds: float = 200) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    old = time.time() - age_seconds
    os.utime(path, (old, old))
    return path


def test_scan_discovers_clip_with_post_copy_and_cover(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    _write_clip(export / "clip-01.mp4")
    (export / "clip-01.jpg").write_bytes(b"cover")
    (export / "clip-01.post.txt").write_text(
        "You Won't Believe This Trick\n"
        "The full story of the trick and why it works.\n"
        "#shorts #viral #lifehack\n",
        encoding="utf-8",
    )

    clips = scan_export_dir(export, min_age_seconds=90)
    assert len(clips) == 1
    discovered = clips[0]
    assert discovered.title == "You Won't Believe This Trick"
    assert discovered.cover_path is not None and discovered.cover_path.suffix == ".jpg"
    assert "full story" in discovered.description
    assert "#shorts" in discovered.instagram_caption
    assert "#shorts #viral #lifehack" in discovered.description


def test_scan_uses_filename_when_no_sidecars(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    clip = _write_clip(export / "my-first-clip.mp4")
    clips = scan_export_dir(export, min_age_seconds=90)
    assert len(clips) == 1
    assert clips[0].mp4_path == clip
    assert clips[0].title == "my-first-clip"
    assert clips[0].cover_path is None


def test_scan_skips_freshly_written_files(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    _write_clip(export / "still-rendering.mp4", age_seconds=5)
    assert scan_export_dir(export, min_age_seconds=90) == []


def test_scan_skips_known_paths(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    clip = _write_clip(export / "old.mp4")
    assert scan_export_dir(export, known_paths={str(clip)}, min_age_seconds=90) == []


def test_scan_enriches_from_clips_json(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    _write_clip(export / "nested" / "clip-07.mp4")
    receipt = {
        "clips": [
            {
                "file": "clip-07.mp4",
                "title": "The Hook Title",
                "postCopy": "Description from the receipt.",
                "source": "Outdoor Boys winter camping",
            }
        ]
    }
    (export / "clips.json").write_text(json.dumps(receipt), encoding="utf-8")

    clips = scan_export_dir(export, min_age_seconds=90)
    assert len(clips) == 1
    assert clips[0].title == "The Hook Title"
    assert clips[0].description == "Description from the receipt."
    assert clips[0].source_label == "Outdoor Boys winter camping"


def test_scan_missing_directory(tmp_path: Path) -> None:
    assert scan_export_dir(tmp_path / "nope") == []
