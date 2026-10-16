"""Cheap change detection for "is the screen doing anything right now?".

The screen-state idea comes from **OpenDesktop**
(https://github.com/atum246/OpenDesktop, MIT) — ``src/screen-state/index.js``:
capture on an interval, reduce each frame to a compact signature, compare it to
the previous one, and only treat the screen as *changed* when the difference
clears a threshold (``diffThreshold: 0.05`` there).  Naveed keeps the rolling
comparison and adds three things a desktop companion needs:

* a byte signature that works with PIL **or** a raw Qt ``QImage`` buffer, so a
  PySide6-only install never needs Pillow just to notice the screen moved;
* an adaptive cadence (:class:`ChangeDetector` reports ``settled`` so the
  watcher can slow its timer while nothing happens, and speed up the moment
  something does);
* a ``scene`` flag for a large-area change, which is what an app switch or a new
  window looks like, versus a caret blinking.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional

from .. import lazy

__all__ = [
    "DEFAULT_COLS",
    "DEFAULT_ROWS",
    "NOISE_FLOOR",
    "SCENE_THRESHOLD",
    "ChangeDetector",
    "ChangeReport",
    "diff_ratio",
    "signature_from_pixels",
    "to_signature",
]

#: Signature resolution: 64x36 keeps a 4K frame under ~2.3k samples.
DEFAULT_COLS = 64
DEFAULT_ROWS = 36

#: Differences below this are anti-aliasing/JPEG-like noise, not real change.
NOISE_FLOOR = 0.02

#: A change this large across the whole frame reads as a new scene (app switch).
SCENE_THRESHOLD = 0.45


def signature_from_pixels(pixels: Any, width: int, height: int, *, cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS) -> bytes:
    """Reduce a raw pixel buffer to a small grayscale signature.

    *pixels* must be tightly packed bytes, one pixel per sample group, ordered
    R,G,B[,A] — which is exactly what ``QImage.constBits()`` (RGB888) and
    ``PIL.Image.tobytes()`` (RGB/RGBA) both hand over.
    """
    if width <= 0 or height <= 0:
        return b""
    data = bytes(pixels)
    channels = max(1, len(data) // (width * height)) if width * height else 3
    channels = min(channels, 4)
    signature = bytearray(cols * rows)
    last_x, last_y = width - 1, height - 1

    for row in range(rows):
        source_y = min(last_y, int((row + 0.5) * height / rows))
        row_offset = source_y * width * channels
        for col in range(cols):
            source_x = min(last_x, int((col + 0.5) * width / cols))
            index = row_offset + source_x * channels
            if index + 2 < len(data):
                r, g, b = data[index], data[index + 1], data[index + 2]
            elif index < len(data):
                r = g = b = data[index]
            else:
                r = g = b = 0
            # Rec. 601 luma, integer maths: fast and plenty for a difference check.
            signature[row * cols + col] = (r * 30 + g * 59 + b * 11) // 100
    return bytes(signature)


def to_signature(image: Any, *, cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS) -> bytes:
    """Signature for a PIL image *or* a Qt ``QImage``.

    Uses PIL's own resize when available (it is much faster than sampling in
    Python); otherwise falls back to :func:`signature_from_pixels` on the raw
    buffer, which keeps the watcher working in a Qt-only install.
    """
    size = getattr(image, "size", None)
    width = height = 0
    if size is not None and not callable(size):
        width, height = int(size[0]), int(size[1])
    elif hasattr(image, "width") and hasattr(image, "height"):
        width, height = int(image.width()), int(image.height())
    if width <= 0 or height <= 0:
        return b""

    PILImage = lazy.optional("PIL.Image")
    if PILImage is not None and hasattr(image, "convert"):
        small = image.convert("L").resize((cols, rows))
        return bytes(small.tobytes())

    if hasattr(image, "constBits") or hasattr(image, "bits"):
        QtImage_Format = lazy.optional("PySide6.QtGui")
        raw = image.constBits() if hasattr(image, "constBits") else image.bits()
        pixels = bytes(raw) if raw is not None else b""
        if QtImage_Format is not None and hasattr(image, "convertToFormat"):
            image = image.convertToFormat(QtImage_Format.QImage.Format.Format_RGB888)
            raw = image.constBits()
            pixels = bytes(raw)
        return signature_from_pixels(pixels, width, height, cols=cols, rows=rows)

    return b""


def diff_ratio(signature_a: bytes, signature_b: bytes) -> float:
    """Mean absolute difference of two signatures, normalised to 0.0 - 1.0."""
    if not signature_a or not signature_b or len(signature_a) != len(signature_b):
        return 1.0
    total = 0
    for left, right in zip(signature_a, signature_b):
        total += abs(left - right)
    return total / (255.0 * len(signature_a))


def frame_hash(signature: bytes) -> str:
    """Stable short hash of a signature (identical-frame fast path)."""
    return hashlib.blake2b(signature, digest_size=8).hexdigest()


@dataclass
class ChangeReport:
    """Outcome of comparing one frame with the running baseline."""

    changed: bool
    ratio: float
    signature: bytes
    frame_hash: str
    scene: bool = False
    settled: bool = False
    stable_frames: int = 0
    first_frame: bool = False

    @property
    def percent(self) -> float:
        return round(self.ratio * 100.0, 2)

    def as_dict(self) -> dict:
        return {
            "changed": self.changed,
            "ratio": round(self.ratio, 4),
            "percent": self.percent,
            "hash": self.frame_hash,
            "scene": self.scene,
            "settled": self.settled,
            "stable_frames": self.stable_frames,
            "first_frame": self.first_frame,
        }


class ChangeDetector:
    """Tracks how much the screen moved since the last interesting frame."""

    def __init__(
        self,
        *,
        noise_floor: float = NOISE_FLOOR,
        scene_threshold: float = SCENE_THRESHOLD,
        settle_frames: int = 3,
    ) -> None:
        self.noise_floor = noise_floor
        self.scene_threshold = scene_threshold
        self.settle_frames = max(1, settle_frames)
        self._baseline: Optional[bytes] = None
        self._last_hash: Optional[str] = None
        self._stable_frames = 0

    def reset(self) -> None:
        self._baseline = None
        self._last_hash = None
        self._stable_frames = 0

    @property
    def baseline(self) -> Optional[bytes]:
        return self._baseline

    def observe(self, signature: bytes) -> ChangeReport:
        """Compare *signature* against the baseline and update the baseline.

        The baseline is only replaced when the change is real, which is what
        turns "the cursor blinked" into "nothing happened" and "a new window
        appeared" into one clean event instead of a burst.
        """
        digest = frame_hash(signature) if signature else ""
        first = self._baseline is None
        if first:
            self._baseline = signature
            self._last_hash = digest
            self._stable_frames = 0
            return ChangeReport(
                changed=True,
                ratio=1.0,
                signature=signature,
                frame_hash=digest,
                scene=True,
                settled=False,
                first_frame=True,
            )

        if digest == self._last_hash:
            self._stable_frames += 1
            return ChangeReport(
                changed=False,
                ratio=0.0,
                signature=signature,
                frame_hash=digest,
                settled=self._stable_frames >= self.settle_frames,
                stable_frames=self._stable_frames,
            )

        ratio = diff_ratio(signature, self._baseline or b"")
        changed = ratio >= self.noise_floor
        if changed:
            self._baseline = signature
            self._stable_frames = 0
        else:
            self._stable_frames += 1
        self._last_hash = digest
        return ChangeReport(
            changed=changed,
            ratio=ratio,
            signature=signature,
            frame_hash=digest,
            scene=ratio >= self.scene_threshold,
            settled=self._stable_frames >= self.settle_frames,
            stable_frames=self._stable_frames,
        )
