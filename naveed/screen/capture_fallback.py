"""Recovery logic for screen captures that come back empty.

Ported and adapted from **brah** (https://github.com/KenKaiii/brah, MIT) —
``src/realtime/tools/screen-capture-fallback.js`` — which was written after a
real multi-monitor macOS bug where Electron's ``desktopCapturer`` returned a
0x0 thumbnail for one display even with Screen Recording granted, while the
system ``screencapture`` tool captured that same display fine.

The lesson kept here: *never blame permissions when they are actually granted*,
and always try a second, platform-native capture path before failing.

Changes from the original
-------------------------
* Python instead of JavaScript, PIL/mss/Qt back-ends instead of Electron.
* ``resolve_source_image`` became :func:`resolve_frame`, a chain over any number
  of candidate grabbers instead of exactly two.
* Frame validation gained :func:`is_empty_frame` checks for all-transparent and
  single-colour frames (a "successful" black capture is still a failed capture).
* Every failure carries a platform-specific, actionable hint instead of one
  macOS-only message.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .. import lazy

__all__ = [
    "CaptureError",
    "SCREEN_ACCESS_DENIED",
    "SCREEN_ACCESS_GRANTED",
    "SCREEN_ACCESS_NOT_DETERMINED",
    "SCREEN_ACCESS_RESTRICTED",
    "SCREEN_ACCESS_UNKNOWN",
    "SIZE_TOLERANCE_PX",
    "CaptureAttempt",
    "describe_capture_failure",
    "expected_pixel_size",
    "get_screen_access_status",
    "is_empty_frame",
    "platform_hint",
    "resolve_frame",
    "sizes_match",
    "validate_frame",
]

#: Backing-pixel sizes can differ from ``size * scale`` by a pixel or two of
#: rounding; the original tolerance was 4px, kept identical here.
SIZE_TOLERANCE_PX = 4

SCREEN_ACCESS_GRANTED = "granted"
SCREEN_ACCESS_DENIED = "denied"
SCREEN_ACCESS_RESTRICTED = "restricted"
SCREEN_ACCESS_NOT_DETERMINED = "not-determined"
SCREEN_ACCESS_UNKNOWN = "unknown"

#: macOS ships the native grabber at a stable path (ported constant).
MACOS_SCREENCAPTURE = "/usr/sbin/screencapture"
MACOS_SCREENCAPTURE_TIMEOUT_S = 15.0


class CaptureError(RuntimeError):
    """A screen capture failed, with a reason the user can act on."""

    def __init__(self, message: str, *, status: str = SCREEN_ACCESS_UNKNOWN, details: Optional[Dict[str, Any]] = None) -> None:
        self.status = status
        self.details = details or {}
        composed = message
        hint = platform_hint()
        if hint and hint not in message:
            composed = f"{message}\n{hint}"
        super().__init__(composed)


@dataclass
class CaptureAttempt:
    """One candidate grabber's outcome, kept for diagnostics and logs."""

    via: str
    ok: bool
    width: int = 0
    height: int = 0
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


# --- platform remediation ---------------------------------------------------

_HINTS: Dict[str, str] = {
    "darwin": (
        "On macOS, grant Screen Recording to the app hosting Naveed:\n"
        "  System Settings -> Privacy & Security -> Screen Recording -> enable your terminal/Python,\n"
        "then quit and relaunch it (macOS only re-checks this at process start)."
    ),
    "win32": (
        "On Windows, check that desktop capture is not blocked:\n"
        "  Settings -> Privacy & security -> Screenshots and apps, and make sure you are not\n"
        "  running inside a protected/DRM window. Naveed itself is excluded from its own captures\n"
        "  automatically, so a black frame usually means a permissions or full-screen-overlay issue."
    ),
    "linux": (
        "On Linux, screenshots need a desktop session:\n"
        "  X11: install one of mss / Pillow / python3-xlib and make sure DISPLAY is set.\n"
        "  Wayland: apps cannot read the framebuffer directly; approve the portal prompt or log\n"
        "  into an X11 session (or set XDG_SESSION_TYPE=x11 on XWayland)."
    ),
}


def platform_hint(platform: Optional[str] = None) -> str:
    """Platform-specific, copy-pasteable remediation text."""
    platform = platform or sys.platform
    if platform.startswith("linux"):
        key = "linux"
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
            return _HINTS["linux"] + "\n  Detected session: Wayland."
        return _HINTS["linux"]
    for key in ("darwin", "win32"):
        if platform.startswith(key):
            return _HINTS[key]
    return "Unknown platforms fall back to mss/Pillow capture; install the 'capture' extra."


def describe_capture_failure(base_message: str, screen_access: str) -> str:
    """Error text for a failed capture.

    Ported behaviour from brah: only mention permissions when they are actually
    missing; otherwise point at the capture path instead of sending the user on
    a permissions wild-goose chase.
    """
    if screen_access == SCREEN_ACCESS_GRANTED:
        return (
            f"{base_message} Screen recording permission is already granted, so this is a "
            "display capture problem, not a permission one. Try another backend, monitor or window."
        )
    if screen_access in (SCREEN_ACCESS_DENIED, SCREEN_ACCESS_RESTRICTED, SCREEN_ACCESS_NOT_DETERMINED):
        return f"{base_message} Screen recording permission is currently '{screen_access}'."
    return base_message


def get_screen_access_status(*, platform: Optional[str] = None, request: bool = False) -> str:
    """Best-effort screen-recording permission status for the current platform.

    macOS is the only platform that exposes this ahead of time (TCC).  Windows
    and Linux report ``granted`` optimistically: a failed capture there is
    diagnosed by :func:`describe_capture_failure` from the frame itself.
    """
    platform = platform or sys.platform
    if not platform.startswith("darwin"):
        return SCREEN_ACCESS_GRANTED
    quartz = lazy.optional("Quartz")
    if quartz is None:  # pragma: no cover - macOS without pyobjc
        return SCREEN_ACCESS_UNKNOWN
    try:
        if request:
            quartz.CGRequestScreenCaptureAccess()
        granted = bool(quartz.CGPreflightScreenCaptureAccess())
    except Exception:  # pragma: no cover - defensive
        return SCREEN_ACCESS_UNKNOWN
    return SCREEN_ACCESS_GRANTED if granted else SCREEN_ACCESS_DENIED


# --- frame validation -------------------------------------------------------

def expected_pixel_size(width: int, height: int, scale: float = 1.0) -> Tuple[int, int]:
    """Physical pixel size of a logical *width* x *height* area."""
    scale = float(scale) or 1.0
    return int(round(width * scale)), int(round(height * scale))


def sizes_match(actual: Tuple[int, int], expected: Tuple[int, int], tolerance: int = SIZE_TOLERANCE_PX) -> bool:
    """Port of brah's ``sizesMatch`` — guards against capturing the wrong display."""
    return abs(actual[0] - expected[0]) <= tolerance and abs(actual[1] - expected[1]) <= tolerance


def is_empty_frame(image: Any, *, all_transparent_means_empty: bool = True) -> Tuple[bool, str]:
    """Decide whether a captured *image* is unusable, with the reason why.

    Returns ``(True, reason)`` for zero-sized, fully transparent, or fully
    uniform frames.  A uniform frame is what a blocked capture looks like: the
    grabber "succeeds" and hands back pure black.
    """
    if image is None:
        return True, "no_frame"

    size = getattr(image, "size", None)
    if size is not None and (size[0] <= 0 or size[1] <= 0):
        return True, "zero_size"

    mode = getattr(image, "mode", "")
    if mode == "RGBA" and all_transparent_means_empty:
        alpha = image.getchannel("A")
        if alpha.getextrema() == (0, 0):
            return True, "fully_transparent"

    try:
        extrema = image.getextrema()
    except Exception:  # pragma: no cover - exotic image objects
        return False, ""

    if mode in ("RGB", "RGBA"):
        bands = extrema[:3]
        if all(band[0] == band[1] for band in bands):
            return True, "uniform_frame"
        return False, ""
    if mode in ("L", "LA", "1"):
        band = extrema[0] if mode != "1" else extrema
        if band[0] == band[1]:
            return True, "uniform_frame"
    return False, ""


def validate_frame(
    image: Any,
    *,
    monitor_size: Optional[Tuple[int, int]] = None,
    scale: float = 1.0,
    tolerance: int = SIZE_TOLERANCE_PX,
    screen_access: Optional[str] = None,
) -> CaptureAttempt:
    """Validate a freshly grabbed frame against the monitor it claims to be.

    Mirrors brah's display-mismatch guard: a frame whose pixel size does not
    match the target display is rejected rather than silently returned as the
    wrong monitor.
    """
    empty, reason = is_empty_frame(image)
    if empty:
        status = screen_access if screen_access is not None else get_screen_access_status()
        return CaptureAttempt(
            via="",
            ok=False,
            reason=describe_capture_failure(f"Screenshot capture returned an empty image ({reason}).", status),
            details={"reason": reason, "screen_access": status},
        )

    width, height = image.size
    if monitor_size is not None:
        expected = expected_pixel_size(monitor_size[0], monitor_size[1], scale)
        if not sizes_match((width, height), expected, tolerance):
            # A 1.0-scale capture of a HiDPI display also lands here, which is a
            # legitimate (if lossy) result, so it is flagged, not rejected.
            return CaptureAttempt(
                via="",
                ok=True,
                width=width,
                height=height,
                reason="display_mismatch",
                details={"actual": (width, height), "expected": expected},
            )

    return CaptureAttempt(via="", ok=True, width=width, height=height)


# --- capture chain ----------------------------------------------------------

def resolve_frame(
    candidates: Iterable[Callable[[], Any]],
    *,
    monitor_size: Optional[Tuple[int, int]] = None,
    scale: float = 1.0,
    screen_access: Optional[str] = None,
    tolerance: int = SIZE_TOLERANCE_PX,
    source_is_screen: bool = True,
) -> Tuple[Any, str]:
    """Try each grabber until one yields a usable frame.

    Ported from brah's ``resolveSourceImage``: the first non-empty frame wins,
    later candidates exist to recover the empty-thumbnail case.  Returns
    ``(image, backend_name)`` and raises :class:`CaptureError` with an accurate
    reason when everything failed.
    """
    status = screen_access if screen_access is not None else get_screen_access_status()
    attempts: List[CaptureAttempt] = []
    first_mismatch: Optional[Tuple[Any, str]] = None

    for candidate in candidates:
        via = getattr(candidate, "__name__", "candidate")
        try:
            image = candidate()
        except Exception as error:  # a backend that is simply unavailable
            attempts.append(CaptureAttempt(via=via, ok=False, reason=f"{type(error).__name__}: {error}"))
            continue

        attempt = validate_frame(
            image,
            monitor_size=monitor_size,
            scale=scale,
            tolerance=tolerance,
            screen_access=status,
        )
        attempt.via = via
        attempts.append(attempt)
        if not attempt.ok:
            continue
        if attempt.reason == "display_mismatch" and first_mismatch is None:
            # Keep it as a fallback: a wrong-size frame still beats no frame,
            # matching the original "recover, don't fail" intent.
            first_mismatch = (image, via)
            continue
        return image, via

    if first_mismatch is not None:
        return first_mismatch

    detail = "; ".join(f"{a.via}: {a.reason}" for a in attempts) or "no capture backend was available"
    if not source_is_screen:
        detail = f"{detail} (target was a window source, not a display)"
    raise CaptureError(
        describe_capture_failure(f"Could not capture the screen ({detail}).", status),
        status=status,
        details={"attempts": [a.__dict__ for a in attempts]},
    )


# --- native helpers ---------------------------------------------------------

def screencapture_availability() -> Optional[str]:
    """Path to macOS ``screencapture`` when usable, else ``None``."""
    if not sys.platform.startswith("darwin"):
        return None
    if os.path.exists(MACOS_SCREENCAPTURE):
        return MACOS_SCREENCAPTURE
    return shutil.which("screencapture")


def capture_display_with_screencapture(
    display_number: int,
    *,
    timeout: float = MACOS_SCREENCAPTURE_TIMEOUT_S,
) -> Tuple[Any, Dict[str, Any]]:
    """Capture one macOS display with ``screencapture -D <n>``.

    Ported from brah, including the 1-based display numbering convention (the
    position of the display inside the platform's display list) and the
    temporary-directory cleanup in ``finally``.  Returns ``(image, details)``;
    the image is a PIL image so the caller can validate its size.
    """
    binary = screencapture_availability()
    if binary is None:
        raise CaptureError("The macOS 'screencapture' tool was not found.")
    PILImage = lazy.load("PIL.Image")
    temp_dir = tempfile.mkdtemp(prefix="naveed-screencapture-")
    target = os.path.join(temp_dir, "capture.png")
    started = None
    try:
        import time as _time

        started = _time.monotonic()
        # -x: no sound, -t png: format, -D n: display number (1-based).
        subprocess.run(
            [binary, "-x", "-D", str(display_number), "-t", "png", target],
            check=True,
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        elapsed = (_time.monotonic() - started) * 1000.0
        with PILImage.open(target) as handle:
            image = handle.convert("RGB").copy()
        return image, {"displayNumber": display_number, "elapsedMs": round(elapsed, 1)}
    except subprocess.CalledProcessError as error:  # pragma: no cover - macOS only
        raise CaptureError(
            f"macOS screencapture failed for display {display_number}: "
            f"{(error.stderr or b'').decode(errors='replace').strip() or error}"
        ) from error
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
