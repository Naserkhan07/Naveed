"""Self-contained Shorts clipper — the cloud-friendly HotClip replacement.

Given one source video it produces exactly what ``shorts_bot.hotclip`` harvests:

  * a vertical 9:16 ``.mp4`` with the highlight window, word-synced captions
    burned in, and loudness normalized to -14 LUFS,
  * a ``<stem>.post.txt`` publish copy (title line + body + hashtags),
  * a ``<stem>.jpg`` cover frame,
  * a ``clips.json`` receipt next to the clips.

Pipeline: faster-whisper transcription with word timestamps → highlight window
scoring → face-guided 9:16 crop (OpenCV haar cascade, center-crop fallback) →
one ffmpeg pass per clip (crop + scale + ASS captions + loudnorm).

Only ``ffmpeg``/``ffprobe`` on PATH plus the optional ``clipper`` extra
(``pip install -e ".[clipper]"`` → faster-whisper, opencv-python-headless) are
required. Heavy imports stay lazy so linting, tests, and the rest of the bot
never need them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
TARGET_LOUDNESS = "-14"
_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9_-]+")

# Package exports; keep the module importable without the heavy extras.
__all__ = [
    "Word",
    "build_ass",
    "chunk_words",
    "clamp_crop_left",
    "escape_ass_text",
    "main",
    "pick_windows",
]


@dataclass(frozen=True, slots=True)
class Word:
    start: float
    end: float
    text: str


# --------------------------------------------------------------------------- #
# small pure helpers (unit-tested, no external tools needed)
# --------------------------------------------------------------------------- #
def safe_stem(name: str) -> str:
    stem = Path(name).stem
    cleaned = _SAFE_STEM_RE.sub("_", stem).strip("_") or "clip"
    return cleaned[:80]


def escape_ass_text(text: str) -> str:
    """Escape a caption chunk for ASS Dialogue text."""
    return (
        text.replace("\\", "\\\\")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", "\\N")
    )


def clamp_crop_left(center_frac: float, source_width: int, crop_width: int) -> int:
    """Left pixel of the crop window so its center stays within the frame."""
    if crop_width >= source_width:
        return 0
    max_left = source_width - crop_width
    raw = int(round(center_frac * source_width - crop_width / 2))
    return max(0, min(max_left, raw))


def chunk_words(
    words: list[Word], max_words: int = 3, max_chars: int = 26
) -> list[tuple[float, float, str]]:
    """Group consecutive words into short caption chunks (start, end, text)."""
    chunks: list[tuple[float, float, str]] = []
    current: list[Word] = []

    def flush() -> None:
        if not current:
            return
        chunks.append((current[0].start, current[-1].end, " ".join(w.text for w in current)))
        current.clear()

    for word in words:
        current.append(word)
        text = " ".join(w.text for w in current)
        if len(current) >= max_words or len(text) >= max_chars:
            flush()
    flush()
    return chunks


def pick_windows(
    words: list[Word],
    duration: float,
    target: float = 45.0,
    max_clips: int = 1,
    min_length: float = 18.0,
) -> list[tuple[float, float, str]]:
    """Choose the best non-overlapping highlight windows from word timings.

    Scores sliding windows by word density, mildly preferring windows that do
    not sit in the very beginning (intros) or the very end (outros). Returns
    ``(start, end, text)`` triples clamped to the file duration.
    """
    if duration <= 0:
        return []
    if not words:
        start = min(duration * 0.15, max(0.0, duration - target))
        end = min(duration, start + target)
        return [(start, end, "")] if end - start >= min_length else []

    intro, outro = duration * 0.08, duration * 0.97
    best: tuple[float, float, float] | None = None  # (score, start, end)
    for i, _word in enumerate(words):
        for j in range(i, len(words)):
            span = words[j].end - words[i].start
            if span > target:
                break
            if span < min_length:
                continue
            count = j - i + 1
            density = count / span
            position = 1.0
            if words[i].start < intro:
                position -= 0.3 * (intro - words[i].start) / max(intro, 1e-6)
            if words[j].end > outro:
                position -= 0.3
            score = density * position
            if best is None or score > best[0]:
                best = (score, words[i].start, words[j].end)

    if best is None:  # too little speech: take the head of the video
        start = words[0].start
        end = min(duration, start + target)
        best = (0.0, start, end)

    chosen: list[tuple[float, float, str]] = []
    start, end = best[1], min(best[2], duration)
    window_words = [w for w in words if w.start >= start and w.end <= end]
    text = " ".join(w.text for w in window_words)
    chosen.append((max(0.0, start), end, text))

    # Optional further windows: continue after the last one with a small gap.
    while len(chosen) < max_clips:
        gap_start = chosen[-1][1] + 5.0
        remaining = [w for w in words if w.start >= gap_start]
        if not remaining or duration - gap_start < min_length:
            break
        nxt = next(
            (w for w in remaining if w.end - remaining[0].start >= min_length), remaining[-1]
        )
        new_start, new_end = remaining[0].start, min(nxt.end, duration)
        if new_end - new_start < min_length or new_start >= duration - 1:
            break
        window_words = [w for w in words if new_start <= w.start and w.end <= new_end]
        chosen.append((new_start, new_end, " ".join(w.text for w in window_words)))
    return chosen


# ASS is a line-oriented subtitle protocol: these two header lines are defined
# by the format itself and cannot be wrapped.
_ASS_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
_ASS_STYLE_LINE = (
    "Style: Caption,DejaVu Sans,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,"
    "&H80000000,-1,0,0,0,100,100,1,0,1,6,2,2,40,40,{margin_v},1"
)


def build_ass(
    chunks: list[tuple[float, float, str]],
    width: int = OUTPUT_WIDTH,
    height: int = OUTPUT_HEIGHT,
    uppercase: bool = True,
) -> str:
    """Render caption chunks as an ASS subtitle script (bottom-center, bold)."""
    margin_v = int(height * 0.14)
    font_size = int(width * 0.075)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        f"{_ASS_STYLE_FORMAT}\n"
        f"{_ASS_STYLE_LINE.format(font_size=font_size, margin_v=margin_v)}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [header]

    def stamp(seconds: float) -> str:
        seconds = max(0.0, seconds)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:05.2f}"

    for start, end, text in chunks:
        body = text.strip()
        if not body:
            continue
        if uppercase:
            body = body.upper()
        lines.append(
            f"Dialogue: 0,{stamp(start)},{stamp(end)},Caption,,0,0,0,,{escape_ass_text(body)}"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# external-tool wrappers (ffmpeg / faster-whisper / opencv)
# --------------------------------------------------------------------------- #
def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True, **kwargs)  # type: ignore[arg-type]


def probe_media(path: Path) -> tuple[float, int, int]:
    """Return ``(duration_seconds, width, height)`` via ffprobe."""
    result = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "format=duration:stream=width,height",
            "-of", "json", str(path),
        ]
    )
    payload = json.loads(result.stdout)
    duration = float(payload.get("format", {}).get("duration") or 0.0)
    width, height = 1920, 1080
    for stream in payload.get("streams", []):
        width = int(stream.get("width") or 1920)
        height = int(stream.get("height") or 1080)
        break
    return duration, width, height


def transcribe(path: Path, model_name: str) -> list[Word]:
    """Word-level transcription via faster-whisper (CPU, int8)."""
    from faster_whisper import WhisperModel  # lazy: heavy extra

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path), word_timestamps=True, vad_filter=True)
    words: list[Word] = []
    for segment in segments:
        for word in segment.words or []:
            text = (word.word or "").strip()
            if text:
                words.append(Word(float(word.start), float(word.end), text))
    return words


def plan_crop(
    path: Path, source_width: int, source_height: int, duration: float, samples: int = 10
) -> int:
    """Detect the horizontal center of faces to guide the 9:16 crop.

    Samples a handful of frames and runs OpenCV's frontal-face cascade over
    them; falls back to the frame center when nothing is found or OpenCV is
    missing. Returns the crop window's left pixel offset.
    """
    # The render filter crops to ih*9/16 x ih, so the window width is a
    # function of the source HEIGHT (e.g. 1280x720 -> 405x720 window).
    crop_width = min(source_width, int(source_height * 9 / 16))
    centers: list[float] = []
    with tempfile.TemporaryDirectory() as tmp:
        for index in range(samples):
            at = duration * (index + 0.5) / samples
            frame = Path(tmp) / f"f{index}.jpg"
            try:
                _run(
                    ["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path),
                     "-frames:v", "1", str(frame)]
                )
            except (subprocess.CalledProcessError, OSError):
                continue
            center = _face_center_x(frame, source_width)
            if center is not None:
                centers.append(center)
    if not centers:
        return clamp_crop_left(0.5, source_width, crop_width)
    average = sum(centers) / len(centers) / source_width
    return clamp_crop_left(average, source_width, crop_width)


def _face_center_x(frame: Path, source_width: int) -> float | None:
    try:
        import cv2  # lazy: heavy extra
    except ImportError:
        return None
    image = cv2.imread(str(frame))
    if image is None:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(60, 60))
    if len(faces) == 0:
        return None
    widest = max(faces, key=lambda box: box[2])
    return float(widest[0] + widest[2] / 2) / max(image.shape[1], 1) * source_width


def render_clip(
    source: Path,
    output: Path,
    start: float,
    length: float,
    crop_left: int,
    ass_path: Path | None,
) -> None:
    """One ffmpeg pass: crop to 9:16, scale, burn captions, normalize loudness."""
    filters = [
        f"crop=ih*9/16:ih:{crop_left}:0",
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}",
    ]
    if ass_path is not None:
        filters.append(f"ass={ass_path.name}")
    filters.append("format=yuv420p")
    command: list[str] = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{max(0.0, start):.2f}", "-i", str(Path(source).resolve()), "-t", f"{length:.2f}",
        "-vf", ",".join(filters),
        "-af", f"loudnorm=I={TARGET_LOUDNESS}:TP=-1.5:LRA=11", "-ar", "48000",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output),
    ]
    _run(command, cwd=str(output.parent))


def write_post_copy(mp4: Path, title: str, body: str) -> None:
    hashtags = os.environ.get("CLIP_HASHTAGS", "#shorts #viral #trending").strip()
    lines = [f"Title: {title}", "", body.strip(), "", hashtags]
    mp4.with_suffix(".post.txt").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def warmup(model_name: str) -> int:
    """Download + load the whisper model so later runs hit the cache."""
    from faster_whisper import WhisperModel  # lazy: heavy extra

    print(f"[clipper] warming model '{model_name}' (downloads once, then cached)…", flush=True)
    WhisperModel(model_name, device="cpu", compute_type="int8")
    print("[clipper] model ready", flush=True)
    return 0


def clip_one(
    source: Path,
    export_dir: Path,
    model_name: str,
    target: float,
    max_clips: int,
) -> list[Path]:
    """Clip one source into export_dir; returns the produced mp4 paths."""
    duration, width, height = probe_media(source)
    words = transcribe(source, model_name)
    windows = pick_windows(words, duration, target=target, max_clips=max_clips)
    if not windows:
        raise RuntimeError("no usable highlight window (video too short or silent)")

    stem = safe_stem(source.name)
    # One folder per source with the exact "clips.json" name — that is the
    # layout shorts_bot.hotclip harvests (export_dir.rglob("clips.json")).
    clip_dir = export_dir / stem
    clip_dir.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    receipt_entries: list[dict] = []

    for index, (start, end, text) in enumerate(windows):
        suffix = "" if index == 0 else f"-{index + 1}"
        mp4 = clip_dir / f"{stem}{suffix}.mp4"
        crop_left = plan_crop(source, width, height, duration)
        ass_path: Path | None = None
        if text:
            chunks = chunk_words(words)
            window_chunks = [c for c in chunks if c[0] >= start - 0.01 and c[1] <= end + 0.01]
            shifted = [(c[0] - start, c[1] - start, c[2]) for c in window_chunks]
            ass_path = mp4.with_suffix(".ass")
            ass_path.write_text(build_ass(shifted), encoding="utf-8")
        try:
            render_clip(source, mp4, start, end - start, crop_left, ass_path)
        finally:
            if ass_path is not None:
                ass_path.unlink(missing_ok=True)

        cover: Path | None = mp4.with_suffix(".jpg")
        try:
            _run(
                ["ffmpeg", "-y", "-v", "error", "-ss", "2", "-i", str(mp4),
                 "-frames:v", "1", "-q:v", "3", str(cover)]
            )
        except (subprocess.CalledProcessError, OSError):
            cover = None

        title = _title_from(text, mp4.stem)
        body = text.strip()[:400] or "(no speech detected)"
        write_post_copy(mp4, title, body)
        receipt_entries.append(
            {
                "file": mp4.name,
                "title": title,
                "description": body,
                "caption": f"{title} {os.environ.get('CLIP_HASHTAGS', '').strip()}".strip(),
                "cover": cover.name if cover else "",
                "source": source.name,
                "start": round(start, 2),
                "end": round(end, 2),
            }
        )
        produced.append(mp4)

    receipt = clip_dir / "clips.json"
    payload = json.dumps({"clips": receipt_entries}, ensure_ascii=False, indent=2)
    receipt.write_text(payload, encoding="utf-8")
    return produced


def _title_from(text: str, fallback: str) -> str:
    words_list = text.split()
    if not words_list:
        return fallback.replace("_", " ").replace("-", " ").title()[:80]
    title = " ".join(words_list[:8]).strip()
    return (title[:77] + "…") if len(title) > 78 else title


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m shorts_bot.clipper")
    sub = parser.add_subparsers(dest="command", required=True)

    warm = sub.add_parser("warmup", help="download the whisper model so later runs are instant")
    warm.add_argument("--model", default=os.environ.get("CLIP_WHISPER_MODEL", "base"))

    do_clip = sub.add_parser("clip", help="clip one source video into vertical Shorts")
    do_clip.add_argument("source", type=Path)
    do_clip.add_argument("--out", type=Path, required=True)
    do_clip.add_argument("--model", default=os.environ.get("CLIP_WHISPER_MODEL", "base"))
    do_clip.add_argument(
        "--target", type=float, default=float(os.environ.get("CLIP_TARGET_SECONDS", "45"))
    )
    do_clip.add_argument(
        "--max-clips", type=int, default=int(os.environ.get("CLIP_MAX_PER_SOURCE", "1"))
    )
    do_clip.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "warmup":
        return warmup(args.model)

    produced = clip_one(args.source, args.out, args.model, args.target, args.max_clips)
    if args.json:
        print(json.dumps({"ok": True, "clips": [str(p) for p in produced]}))
    else:
        for path in produced:
            print(f"[clipper] wrote {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"[clipper] external tool failed: {exc.cmd}\n{exc.stderr[-2000:]}", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:
        print(f"[clipper] failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
