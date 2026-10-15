"""Screen capture with a backend chain and self-exclusion.

The chain, the recovery behaviour and the "never blame permissions when they are
granted" error text come from **brah** (https://github.com/KenKaiii/brah, MIT),
generalised from Electron's ``desktopCapturer``-then-``screencapture`` pair into
an ordered list of backends (:class:`MssBackend`, :class:`QtScreenBackend`,
:class:`PillowBackend`, :class:`MacScreencaptureBackend`).

Two extra pieces make this usable by a *companion that lives on the screen*:

* **Self-exclusion.**  Naveed floats above the desktop, so a naive capture would
  photograph the mascot and the model would start clicking on it.  The service
  hides the overlay for the duration of the grab (``hide_overlay`` callback) and
  the Windows overlay additionally sets ``WDA_EXCLUDEFROMCAPTURE``.
* **One frame per need.**  ``ttl_seconds`` caches the last grab for a fraction of
  a second, so a burst of questions ("what is on screen?" asked twice) does not
  hammer the compositor.
"""

from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import lazy
from . import capture_fallback
from .displays import Monitor, monitors_or_default, primary_monitor
from .focus import ActiveWindow
from .retention import ScreenshotStore

__all__ = [
    "CaptureError",
    "CaptureService",
    "Frame",
    "MacScreencaptureBackend",
    "MssBackend",
    "PillowBackend",
    "QtScreenBackend",
    "available_backends",
]

CaptureError = capture_fallback.CaptureError


@dataclass
class Frame:
    """One captured screen image plus where it came from."""

    image: Any
    width: int
    height: int
    monitor: Monitor
    via: str = ""
    captured_at: float = field(default_factory=time.time)
    saved_path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.captured_at)

    def png_bytes(self) -> bytes:
        """PNG payload, whichever image type the backend produced."""
        image = self.image
        if isinstance(image, (bytes, bytearray)):
            return bytes(image)
        if hasattr(image, "save"):  # PIL
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            return stream.getvalue()
        QtCore = lazy.load("PySide6.QtCore", extra="ui")
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.data())

    def signature(self, *, cols: int = 64, rows: int = 36) -> bytes:
        from .diff import to_signature

        return to_signature(self.image, cols=cols, rows=rows)

    def save(self, directory: str, *, name: Optional[str] = None) -> str:
        store = ScreenshotStore(directory)
        self.saved_path = store.save_bytes(self.png_bytes(), name=name)
        return self.saved_path


# --- backends ---------------------------------------------------------------

class _Backend:
    """A named way to grab one monitor."""

    name = "backend"

    def available(self) -> bool:  # pragma: no cover - trivial
        raise NotImplementedError

    def grab(self, monitor: Monitor) -> Tuple[Any, str]:
        """Return ``(image, mode)`` where mode is ``pil`` or ``qt``."""
        raise NotImplementedError


class MssBackend(_Backend):
    """Fast cross-platform grabber (X11, Windows, macOS)."""

    name = "mss"

    def available(self) -> bool:
        return lazy.find_spec_safe("mss") is not None

    def grab(self, monitor: Monitor) -> Tuple[Any, str]:
        mss = lazy.load("mss", extra="capture")
        PILImage = lazy.load("PIL.Image", extra="capture")
        with mss.mss() as handle:
            # mss.monitors[0] is the virtual desktop; real displays start at 1.
            index = min(monitor.index + 1, len(handle.monitors) - 1)
            shot = handle.grab(handle.monitors[index])
            image = PILImage.frombytes("RGB", shot.size, shot.rgb)
        return image, "pil"


class QtScreenBackend(_Backend):
    """Grabs through Qt, so it shares the overlay's own coordinate space.

    Only usable when a ``QGuiApplication`` already exists; a headless watcher
    should never spin one up just to take a screenshot.
    """

    name = "qt"

    def available(self) -> bool:
        if lazy.find_spec_safe("PySide6.QtGui") is None:
            return False
        QtGui = lazy.load("PySide6.QtGui", extra="ui")
        return QtGui.QGuiApplication.instance() is not None

    def grab(self, monitor: Monitor) -> Tuple[Any, str]:
        QtGui = lazy.load("PySide6.QtGui", extra="ui")
        screens = QtGui.QGuiApplication.screens()
        if not screens:
            raise CaptureError("Qt reported no screens.")
        screen = screens[min(monitor.index, len(screens) - 1)]
        pixmap = screen.grabWindow(0)
        image = pixmap.toImage()
        if image.isNull():
            raise CaptureError("Qt returned a null image for this screen.")
        return image, "qt"


class PillowBackend(_Backend):
    """``PIL.ImageGrab`` — slowest, but present on almost every install."""

    name = "pillow"

    def available(self) -> bool:
        if lazy.find_spec_safe("PIL.ImageGrab") is None:
            return False
        import sys as _sys

        if _sys.platform.startswith("linux"):
            # ImageGrab on Linux needs X11 and a working X display.
            import os as _os

            return bool(_os.environ.get("DISPLAY"))
        return True

    def grab(self, monitor: Monitor) -> Tuple[Any, str]:
        ImageGrab = lazy.load("PIL.ImageGrab", extra="capture")
        bbox = (monitor.x, monitor.y, monitor.right, monitor.bottom)
        try:
            image = ImageGrab.grab(bbox=bbox, all_screens=True)
        except TypeError:  # older Pillow without all_screens
            image = ImageGrab.grab(bbox=bbox)
        return image, "pil"


class MacScreencaptureBackend(_Backend):
    """Native ``screencapture`` path, ported from brah's fallback."""

    name = "screencapture"

    def available(self) -> bool:
        return capture_fallback.screencapture_availability() is not None

    def grab(self, monitor: Monitor) -> Tuple[Any, str]:
        image, _details = capture_fallback.capture_display_with_screencapture(monitor.index + 1)
        return image, "pil"


def available_backends(*, include_qt: bool = True) -> List[_Backend]:
    """Backends that are usable right now, in preference order."""
    candidates: Sequence[_Backend] = (
        MssBackend(),
        QtScreenBackend(),
        PillowBackend(),
        MacScreencaptureBackend(),
    )
    result: List[_Backend] = []
    for backend in candidates:
        if backend.name == "qt" and not include_qt:
            continue
        try:
            if backend.available():
                result.append(backend)
        except Exception:
            continue
    return result


# --- service ----------------------------------------------------------------

class CaptureService:
    """Grabs monitors, saves them through the store and never sees itself."""

    def __init__(
        self,
        *,
        store: Optional[ScreenshotStore] = None,
        prefer: Optional[Sequence[str]] = None,
        hide_overlay: Optional[Callable[[], None]] = None,
        show_overlay: Optional[Callable[[], None]] = None,
        ttl_seconds: float = 0.35,
        max_width: int = 1920,
    ) -> None:
        self.store = store
        self.hide_overlay = hide_overlay
        self.show_overlay = show_overlay
        self.ttl_seconds = max(0.0, ttl_seconds)
        self.max_width = max_width
        self._prefer = list(prefer) if prefer else []
        self._lock = threading.RLock()
        self._cached: Optional[Frame] = None
        self._last_backend = ""
        self._stats: Dict[str, int] = {"captures": 0, "failures": 0, "reused": 0, "saved": 0}

    # --- backends -----------------------------------------------------
    def backends(self) -> List[_Backend]:
        """Usable backends ordered by preference and by what worked last."""
        candidates = available_backends()
        order: Dict[str, int] = {}
        for position, name in enumerate(self._prefer):
            order[name] = position
        if self._last_backend:
            order.setdefault(self._last_backend, len(order))
        candidates.sort(key=lambda backend: order.get(backend.name, 100))
        return candidates

    @property
    def backend_names(self) -> List[str]:
        return [backend.name for backend in self.backends()]

    # --- grabbing -----------------------------------------------------
    def _grab_with(self, monitor: Monitor) -> Tuple[Any, str]:
        backends = self.backends()
        if not backends:
            raise CaptureError(
                "No screen capture backend is available (install the 'capture' extra: mss + Pillow)."
            )

        def candidate_iterator():
            for backend in backends:
                def grab(backend=backend) -> Any:
                    image, _mode = backend.grab(monitor)
                    return image

                grab.__name__ = backend.name
                yield grab

        try:
            image, via = capture_fallback.resolve_frame(
                candidate_iterator(),
                monitor_size=(monitor.width, monitor.height),
                scale=monitor.scale,
                source_is_screen=True,
            )
        except CaptureError:
            self._stats["failures"] += 1
            raise

        self._last_backend = via
        size = self._image_size(image)
        metadata: Dict[str, Any] = {}
        expected = capture_fallback.expected_pixel_size(monitor.width, monitor.height, monitor.scale)
        if not capture_fallback.sizes_match(size, expected):
            # Reported, not fatal: a 1x grab of a 2x display is still usable, and
            # Monitor.to_global() rescales model coordinates using the real size.
            metadata["dpi_mismatch"] = {"actual": size, "expected": expected, "scale": monitor.scale}
        return image, via, metadata

    @staticmethod
    def _image_size(image: Any) -> Tuple[int, int]:
        size = getattr(image, "size", None)
        if size is not None and not callable(size):
            return int(size[0]), int(size[1])
        if hasattr(image, "width") and hasattr(image, "height"):
            return int(image.width()), int(image.height())
        return (0, 0)

    def _resize(self, image: Any, width_limit: int) -> Any:
        """Downscale oversized frames so prompts and disk stay small."""
        size = self._image_size(image)
        if size[0] <= width_limit or size[0] <= 0:
            return image
        ratio = width_limit / float(size[0])
        new_size = (width_limit, max(1, int(size[1] * ratio)))
        if hasattr(image, "resize"):
            return image.resize(new_size)
        QtCore = lazy.load("PySide6.QtCore", extra="ui")
        return image.scaled(
            new_size[0],
            new_size[1],
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

    def capture(
        self,
        monitor: Optional[Monitor] = None,
        *,
        save: bool = False,
        protect: bool = False,
        fresh: bool = False,
        resize: bool = True,
    ) -> Frame:
        """Capture one monitor.

        ``fresh=True`` bypasses the tiny TTL cache — used by the agent right
        after it acts, because then the previous frame is actively misleading.
        """
        target = monitor or primary_monitor(monitors_or_default())
        with self._lock:
            cached = self._cached
            if not fresh and cached is not None and cached.age <= self.ttl_seconds and cached.monitor.index == target.index:
                self._stats["reused"] += 1
                return cached

            hidden = False
            if self.hide_overlay is not None:
                try:
                    self.hide_overlay()
                    hidden = True
                except Exception:
                    hidden = False
            try:
                image, via, metadata = self._grab_with(target)
            finally:
                if hidden and self.show_overlay is not None:
                    try:
                        self.show_overlay()
                    except Exception:
                        pass

            width, height = self._image_size(image)
            if resize:
                image = self._resize(image, self.max_width)
                width, height = self._image_size(image)

            frame = Frame(
                image=image,
                width=width,
                height=height,
                monitor=target,
                via=via,
                metadata=metadata,
            )
            self._stats["captures"] += 1

            if save and self.store is not None:
                try:
                    frame.saved_path = self.store.save_image(image, protect=protect)
                    self._stats["saved"] += 1
                except Exception:
                    frame.saved_path = ""

            self._cached = frame
            return frame

    def capture_for_window(
        self,
        window: Optional[ActiveWindow] = None,
        *,
        monitors: Optional[Sequence[Monitor]] = None,
        **kwargs: Any,
    ) -> Frame:
        """Capture the monitor showing most of *window* (voiceuse's targeting rule)."""
        monitors = list(monitors or monitors_or_default())
        window = window or ActiveWindow()
        target = window.monitor(monitors) if window.rect else primary_monitor(monitors)
        return self.capture(target, **kwargs)

    # --- helpers ------------------------------------------------------
    def screen_access_status(self) -> str:
        return capture_fallback.get_screen_access_status()

    def stats(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = dict(self._stats)
        payload["backends"] = self.backend_names
        payload["last_backend"] = self._last_backend
        payload["screen_access"] = self.screen_access_status()
        if self.store is not None:
            payload["store"] = self.store.stats()
        return payload

    def invalidate(self) -> None:
        """Forget the cached frame (call after the agent acts)."""
        with self._lock:
            self._cached = None
