from __future__ import annotations

from pathlib import Path

import pytest

from shorts_bot.models import WordCue
from shorts_bot.subtitles import (
    HIGHLIGHT_COLOURS,
    SubtitleStyle,
    build_ass,
    chunk_words,
    resolve_font_name,
    words_in_window,
    write_clip_ass,
)

WORDS = [
    WordCue("you", 0.30, 0.72),
    WordCue("gotta", 0.85, 1.27),
    WordCue("be", 1.40, 1.82),
    WordCue("like,", 1.95, 2.37),
    WordCue("water", 2.50, 2.92),
    WordCue("my", 3.05, 3.47),
    WordCue("{friend}", 3.60, 4.02),
    WordCue("how", 4.15, 4.57),
    WordCue("you", 4.70, 5.12),
    WordCue("do", 5.25, 5.67),
    WordCue("it", 5.80, 6.22),
    WordCue("you", 6.35, 6.77),
]


def style(**kwargs) -> SubtitleStyle:
    return SubtitleStyle(font_name="TestFont", font_size=64, **kwargs)


def test_words_in_window_rebases_and_filters() -> None:
    window = words_in_window(WORDS, 2.50, 2.20)
    assert [word.word for word in window] == ["water", "my", "{friend}", "how"]
    assert window[0].start_seconds == 0.0
    assert window[0].end_seconds == pytest.approx(0.42)


def test_chunk_words_groups_and_sanitises() -> None:
    chunks = chunk_words(WORDS, max_words=4)
    assert [[cue.word for cue in chunk] for chunk in chunks] == [
        ["YOU", "GOTTA", "BE", "LIKE"],
        ["WATER", "MY", "FRIEND", "HOW"],
        ["YOU", "DO", "IT", "YOU"],
    ]


def test_chunk_words_respects_character_limit() -> None:
    long_words = [WordCue("extraordinary", i * 0.5, i * 0.5 + 0.4) for i in range(6)]
    chunks = chunk_words(long_words, max_words=4, max_chars=24)
    assert all(len(chunk) <= 1 for chunk in chunks)


def test_build_ass_contains_styles_and_per_word_events() -> None:
    ass = build_ass(WORDS[:4], style())
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert HIGHLIGHT_COLOURS["cyan"] in ass
    assert HIGHLIGHT_COLOURS["yellow"] in ass
    assert "CaptionGlow" in ass
    assert "\\blur5" in ass
    # One word event per word plus one glow event.
    assert ass.count("Dialogue:") == 5
    # First word highlighted in first event, others white.
    first_event = [
        line
        for line in ass.splitlines()
        if line.startswith("Dialogue:") and "\\1c" in line
    ][0]
    assert "{\\1c&H00FFE500\\fscx108\\fscy108}YOU" in first_event
    assert "{\\1c&H00FFFFFF}GOTTA" in first_event
    # Entry pop transform on the first word event only.
    assert "\\t(0,140,\\fscx100\\fscy100)" in first_event


def test_build_ass_alternates_highlight_per_chunk() -> None:
    ass = build_ass(WORDS, style())
    caption0_events = [
        line
        for line in ass.splitlines()
        if line.startswith("Dialogue:") and ",Caption0," in line
    ]
    assert caption0_events
    # Chunk 1 uses Caption0 (cyan); its first word event highlights YOU.
    assert any(
        "{\\1c&H00FFE500\\fscx108\\fscy108}YOU" in line for line in caption0_events
    )
    assert not any(
        "{\\1c&H00FFE500\\fscx108\\fscy108}WATER" in line for line in caption0_events
    )
    caption1_events = [
        line
        for line in ass.splitlines()
        if line.startswith("Dialogue:") and ",Caption1," in line
    ]
    assert any(
        "{\\1c&H0000EBFF\\fscx108\\fscy108}WATER" in line for line in caption1_events
    )


def test_build_ass_times_word_events_between_word_starts() -> None:
    ass = build_ass(WORDS[:2], style())
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue: 1")]
    assert lines[0].startswith("Dialogue: 1,0:00:00.30,0:00:00.85,")
    assert lines[1].startswith("Dialogue: 1,0:00:00.85,0:00:01.27,")


def test_write_clip_ass_writes_file(tmp_path: Path) -> None:
    output = write_clip_ass(WORDS, 0.0, 7.0, tmp_path / "clip.ass", style())
    assert output.exists()
    assert "[Script Info]" in output.read_text(encoding="utf-8")


def test_resolve_font_name_prefers_requested(tmp_path: Path) -> None:
    (tmp_path / "Anton-Regular.ttf").write_bytes(b"font")
    assert resolve_font_name(tmp_path, "Anton") == "Anton"


def test_resolve_font_name_falls_back_to_dejavu(tmp_path: Path) -> None:
    (tmp_path / "DejaVuSans-Bold.ttf").write_bytes(b"font")
    assert resolve_font_name(tmp_path, "Anton") == "DejaVu Sans"


def test_resolve_font_name_without_directory(tmp_path: Path) -> None:
    assert resolve_font_name(tmp_path / "missing", "Anton") == "Anton"
