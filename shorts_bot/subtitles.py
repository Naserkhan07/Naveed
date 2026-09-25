"""Word-synced karaoke subtitle rendering for Shorts/Reels.

Builds ASS (Advanced SubStation Alpha) caption scripts with word-by-word
highlight sweeps, sizing and kinetic entry animation, then lets
:class:`~shorts_bot.media.MediaProcessor` burn them into the rendered clip.

The look: all-caps heavy condensed type, white words with the currently
spoken word lit in cyan or yellow, thick black outline, dark drop shadow
and a soft glow — the classic viral creator caption style.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import WordCue

# ASS colours are &HAABBGGRR (alpha, blue, green, red).
_WHITE = "&H00FFFFFF"
_BLACK = "&H00000000"
_SHADOW = "&H88000000"
HIGHLIGHT_COLOURS: dict[str, str] = {
    # Bright cyan in RGB (0, 229, 255) -> BGR.
    "cyan": "&H00FFE500",
    # Bright yellow in RGB (255, 235, 0) -> BGR.
    "yellow": "&H0000EBFF",
}
_DEFAULT_HIGHLIGHTS = ("cyan", "yellow")

_CANVAS_WIDTH = 1080
_CANVAS_HEIGHT = 1920


@dataclass(frozen=True, slots=True)
class SubtitleStyle:
    font_name: str = "Anton"
    font_size: int = 62
    position_y: int = 850
    highlight_names: tuple[str, ...] = _DEFAULT_HIGHLIGHTS
    words_per_screen: int = 4
    max_chars_per_line: int = 26

    @property
    def highlights(self) -> tuple[str, ...]:
        resolved = tuple(
            HIGHLIGHT_COLOURS[name]
            for name in self.highlight_names
            if name in HIGHLIGHT_COLOURS
        )
        return resolved or (HIGHLIGHT_COLOURS["cyan"],)


_WORD_SANITIZE = re.compile(r"[{}\n\r]")
# Strip leading noise (braces, quotes, hashtags) and trailing noise (anything
# that is not a word character or intentional !/?). Internal apostrophes,
# hyphens and punctuation survive.
_WORD_STRIP = re.compile(r"^[^\w'’&@-]+|[^\w?!]+$", re.UNICODE)
_CHARS_LIMIT = 28  # absolute ceiling for one caption line in all caps


def _clean_word(word: str) -> str:
    cleaned = _WORD_SANITIZE.sub("", word).strip()
    cleaned = _WORD_STRIP.sub("", cleaned)
    return cleaned.upper()


def _format_time(seconds: float) -> str:
    clamped = max(0.0, seconds)
    total_centiseconds = int(round(clamped * 100))
    hours, remainder = divmod(total_centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def words_in_window(
    words: tuple[WordCue, ...] | list[WordCue],
    start_seconds: float,
    duration_seconds: float,
) -> list[WordCue]:
    """Words spoken inside one clip, rebased so the clip starts at 0."""
    end_seconds = start_seconds + duration_seconds
    selected: list[WordCue] = []
    for cue in words:
        midpoint = (cue.start_seconds + cue.end_seconds) / 2
        if midpoint < start_seconds or midpoint >= end_seconds:
            continue
        selected.append(
            WordCue(
                word=cue.word,
                start_seconds=max(0.0, cue.start_seconds - start_seconds),
                end_seconds=max(0.0, cue.end_seconds - start_seconds),
            )
        )
    return selected


def chunk_words(
    words: list[WordCue],
    max_words: int = 4,
    max_chars: int = 24,
) -> list[list[WordCue]]:
    """Group consecutive words into short on-screen caption chunks."""
    chunks: list[list[WordCue]] = []
    current: list[WordCue] = []
    current_chars = 0
    for cue in words:
        display = _clean_word(cue.word)
        if not display:
            continue
        projected = current_chars + len(display) + (1 if current else 0)
        if current and (len(current) >= max_words or projected > max_chars):
            chunks.append(current)
            current = []
            current_chars = 0
            projected = len(display)
        current.append(WordCue(display, cue.start_seconds, cue.end_seconds))
        current_chars = projected
    if current:
        chunks.append(current)
    return chunks


def _word_window(
    chunk: list[WordCue],
    word_index: int,
    chunk_end: float,
) -> tuple[float, float]:
    cue = chunk[word_index]
    start = cue.start_seconds
    if word_index + 1 < len(chunk):
        end = chunk[word_index + 1].start_seconds
    else:
        end = max(cue.end_seconds, chunk_end)
    if end <= start:
        end = start + 0.2
    return start, end


def _highlight_text(
    chunk: list[WordCue],
    active_index: int,
    highlight: str,
) -> str:
    """The chunk line with the active word coloured and gently scaled up.

    Every word event re-typesets the identical line, so overlapping events
    stay pixel-aligned while the highlight position moves word by word.
    """
    parts: list[str] = []
    for index, cue in enumerate(chunk):
        if index == active_index:
            parts.append(f"{{\\1c{highlight}\\fscx108\\fscy108}}{cue.word}")
        else:
            parts.append(f"{{\\1c{_WHITE}}}{cue.word}")
    return " ".join(parts)


def _chunk_bounds(chunk: list[WordCue], next_chunk: list[WordCue] | None) -> tuple[float, float]:
    start = chunk[0].start_seconds
    end = next_chunk[0].start_seconds if next_chunk else chunk[-1].end_seconds
    end = max(end, chunk[-1].end_seconds)
    return start, end


def resolve_font_name(font_dir: Path, preferred: str) -> str:
    """Prefer the requested font family; fall back to the bundled DejaVu Bold."""
    if font_dir.is_dir():
        for font_file in sorted(font_dir.iterdir()):
            if font_file.suffix.lower() in {".ttf", ".otf"} and preferred.casefold().replace(
                " ", ""
            ) in font_file.stem.casefold().replace("-", "").replace(" ", ""):
                return preferred
        for font_file in sorted(font_dir.iterdir()):
            if "dejavusansbold" in font_file.stem.casefold().replace("-", ""):
                return "DejaVu Sans"
    return preferred


def build_ass(words: list[WordCue], style: SubtitleStyle) -> str:
    """Build a complete ASS subtitle script for one rendered clip."""
    chunks = chunk_words(
        words,
        max_words=max(1, style.words_per_screen),
        max_chars=min(_CHARS_LIMIT, style.max_chars_per_line),
    )
    highlights = style.highlights

    styles_block: list[str] = []
    for variant_index, highlight in enumerate(highlights):
        styles_block.append(
            "Style: "
            f"Caption{variant_index},{style.font_name},{style.font_size},"
            f"{_WHITE},{highlight},{_BLACK},{_SHADOW},"
            "-1,0,0,0,100,100,0,0,1,4.5,2,5,90,90,50,1"
        )
    glow_outline = max(6.0, style.font_size * 0.12)
    styles_block.append(
        "Style: "
        f"CaptionGlow,{style.font_name},{style.font_size},"
        f"&HDFFFFFFF,&H64FFFFFF,{_BLACK},{_SHADOW},"
        f"-1,0,0,0,100,100,0,0,1,{glow_outline:g},0,5,90,90,50,1"
    )

    dialogues: list[str] = []
    for index, chunk in enumerate(chunks):
        following = chunks[index + 1] if index + 1 < len(chunks) else None
        start, end = _chunk_bounds(chunk, following)
        if end <= start:
            end = start + 0.25
        start_text = _format_time(start)
        end_text = _format_time(end)
        line = " ".join(cue.word for cue in chunk)
        if not line:
            continue
        position = f"\\an5\\pos({_CANVAS_WIDTH // 2},{style.position_y})"
        highlight = highlights[index % len(highlights)]
        dialogues.append(
            f"Dialogue: 0,{start_text},{end_text},CaptionGlow,,0,0,0,,"
            f"{{{position}\\blur5}}{line}"
        )
        variant = index % len(highlights)
        for word_index in range(len(chunk)):
            word_start, word_end = _word_window(chunk, word_index, end)
            # The first word event of a chunk also carries the entry pop:
            # the whole line briefly scales up, then settles at 100%.
            entry = (
                "\\fscx112\\fscy112\\t(0,140,\\fscx100\\fscy100)"
                if word_index == 0
                else ""
            )
            dialogues.append(
                f"Dialogue: 1,{_format_time(word_start)},{_format_time(word_end)},"
                f"Caption{variant},,0,0,0,,"
                f"{{{position}{entry}}}{_highlight_text(chunk, word_index, highlight)}"
            )

    return (
        "[Script Info]\n"
        "Title: ShortsBot word-synced captions\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {_CANVAS_WIDTH}\n"
        f"PlayResY: {_CANVAS_HEIGHT}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
        "MarginV, Encoding\n"
        + "\n".join(styles_block)
        + "\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(dialogues)
        + ("\n" if dialogues else "")
    )


def write_clip_ass(
    words: tuple[WordCue, ...] | list[WordCue],
    start_seconds: float,
    duration_seconds: float,
    output_path: Path,
    style: SubtitleStyle,
) -> Path:
    """Write the ASS subtitle file for one clip window."""
    clip_words = words_in_window(words, start_seconds, duration_seconds)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_ass(clip_words, style), encoding="utf-8")
    return output_path
