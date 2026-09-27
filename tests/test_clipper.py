"""Tests for the built-in clipper (pure logic — no ffmpeg/models needed)."""

from __future__ import annotations

import json

import pytest

from shorts_bot.clipper import (
    Word,
    _title_from,
    build_ass,
    chunk_words,
    clamp_crop_left,
    escape_ass_text,
    pick_windows,
    safe_stem,
    write_post_copy,
)


def _words(specs: list[tuple[float, float, str]]) -> list[Word]:
    return [Word(start, end, text) for start, end, text in specs]


def test_safe_stem_sanitizes_and_truncates() -> None:
    # Consecutive invalid characters collapse into one underscore.
    assert safe_stem("My Video: Part 1?.mp4") == "My_Video_Part_1"
    assert safe_stem("???") == "clip"
    assert len(safe_stem("x" * 500)) == 80


def test_escape_ass_text() -> None:
    assert escape_ass_text("a{b}c\\d\ne") == "a(b)c\\\\d\\Ne"


def test_clamp_crop_left() -> None:
    # 1920-wide source, 9:16 crop = 1080 wide
    assert clamp_crop_left(0.5, 1920, 1080) == 420
    assert clamp_crop_left(0.0, 1920, 1080) == 0
    assert clamp_crop_left(1.0, 1920, 1080) == 840
    assert clamp_crop_left(0.1, 1920, 1080) == 0  # clamped, no negative
    assert clamp_crop_left(0.5, 1000, 1080) == 0  # crop >= width
    assert clamp_crop_left(0.5, 1080, 1080) == 0


def test_chunk_words_groups_of_three() -> None:
    words = _words([(i, i + 0.5, f"w{i}") for i in range(7)])
    chunks = chunk_words(words, max_words=3)
    assert [c[2] for c in chunks] == ["w0 w1 w2", "w3 w4 w5", "w6"]
    assert chunks[0][0] == 0 and chunks[-1][1] == 6.5


def test_pick_windows_picks_densest_middle_window() -> None:
    # Sparse words at the start (intro), dense in the middle, tail after end.
    words = _words([(i * 2.0, i * 2.0 + 0.5, "a") for i in range(5)])  # 0..9s sparse
    words += _words([(30.0 + i, 30.5 + i, "b") for i in range(20)])  # 30..49.5 dense
    windows = pick_windows(words, duration=120.0, target=25.0)
    assert len(windows) == 1
    start, end, text = windows[0]
    assert 18.0 <= end - start <= 28.0  # window spans word timings, not padding
    assert start >= 25.0  # skipped the intro
    assert "b" in text


def test_pick_windows_multiple_non_overlapping() -> None:
    words = _words(
        [(i, i + 0.9, "w") for i in range(0, 60, 1)]  # 0..60s
        + [(100 + i, 100.9 + i, "x") for i in range(0, 60, 1)]  # 100..160s
    )
    windows = pick_windows(words, duration=200.0, target=40.0, max_clips=2)
    assert len(windows) == 2
    assert windows[0][1] + 5.0 <= windows[1][0]  # gap between windows
    for start, end, _ in windows:
        assert 0 <= start < end <= 200.0


def test_pick_windows_no_words_falls_back_inside_duration() -> None:
    windows = pick_windows([], duration=300.0, target=45.0)
    assert len(windows) == 1
    start, end, text = windows[0]
    assert text == ""
    assert 0 <= start < end <= 300.0
    assert end - start == pytest.approx(45.0)


def test_pick_windows_too_short_video_without_words() -> None:
    assert pick_windows([], duration=5.0, target=45.0) == []


def test_build_ass_contains_events_and_defaults() -> None:
    script = build_ass([(1.0, 3.5, "hello world"), (4.0, 6.0, "second caption")])
    assert "PlayResX: 1080" in script
    assert "PlayResY: 1920" in script
    assert "Style: Caption,DejaVu Sans," in script
    assert "Dialogue: 0,0:00:01.00,0:00:03.50,Caption" in script
    assert "HELLO WORLD" in script  # uppercase by default
    assert "SECOND CAPTION" in script


def test_write_post_copy_shape(tmp_path) -> None:
    import os

    mp4 = tmp_path / "clip.mp4"
    os.environ["CLIP_HASHTAGS"] = "#shorts #test"
    try:
        write_post_copy(mp4, "My Title", "Body text here")
    finally:
        del os.environ["CLIP_HASHTAGS"]
    raw = mp4.with_suffix(".post.txt").read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    assert lines[0] == "Title: My Title"
    assert "Body text here" in lines
    assert lines[-1] == "#shorts #test"


def test_title_from_text() -> None:
    assert _title_from("one two three four", "fb") == "one two three four"
    long = " ".join(f"word{i}" for i in range(30))
    title = _title_from(long, "fb")
    assert len(title) <= 78
    assert _title_from("", "some_file-name") == "Some File Name"


def test_receipt_roundtrip_matches_harvester(tmp_path) -> None:
    """The receipt layout we write must be readable by shorts_bot.hotclip."""
    from shorts_bot.hotclip import _clips_json_index

    entry = {"file": "clip.mp4", "title": "T", "description": "D", "cover": "clip.jpg"}
    receipt = tmp_path / "mysource" / "clips.json"  # exact name the harvester rglobs
    receipt.parent.mkdir()
    receipt.write_text(json.dumps({"clips": [entry]}), encoding="utf-8")
    index = _clips_json_index(tmp_path)
    assert index.get("clip.mp4") == entry
