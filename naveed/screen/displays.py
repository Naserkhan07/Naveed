"""Monitor geometry and global-coordinate maths.

Derived from **voice-computer-use-agent**
(https://github.com/jarmen423/voice-computer-use-agent, MIT) —
``voiceuse/vision_bridge.py::_capture_target`` and ``voiceuse/os_controller.py``
— which solved the two problems that break naive screen agents:

1. **Which monitor.**  The original captured only the monitor containing the
   target window.  Naveed keeps that idea and picks the monitor with the largest
   *area* overlap instead of the first monitor containing the window's origin;
   a window straddling two displays then resolves to the one that is actually
   showing most of it.
2. **Local vs global coordinates.**  A screenshot is a monitor-local bitmap,
   while mouse input is global.  The original tracked ``origin_x``/``origin_y``
   per capture target; :meth:`Monitor.to_global` does the same, and additionally
   handles the HiDPI case where the captured bitmap is larger than the logical
   monitor (retina/150% scaling), so a click lands where the model pointed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .. import lazy

__all__ = [
    "Monitor",
    "list_monitors",
    "monitor_at_point",
    "monitor_for_rect",
    "monitors_or_default",
    "primary_monitor",
    "virtual_desktop",
]

Rect = Tuple[int, int, int, int]  # x, y, width, height


@dataclass(frozen=True)
class Monitor:
    """One display in the virtual desktop, in global logical coordinates."""

    index: int
    x: int
    y: int
    width: int
    height: int
    scale: float = 1.0
    name: str = ""
    is_primary: bool = False

    # --- geometry -----------------------------------------------------
    @property
    def rect(self) -> Rect:
        return (self.x, self.y, self.width, self.height)

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def contains_point(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def intersection_area(self, rect: Rect) -> int:
        rx, ry, rw, rh = rect
        left = max(self.x, rx)
        top = max(self.y, ry)
        right = min(self.right, rx + rw)
        bottom = min(self.bottom, ry + rh)
        if right <= left or bottom <= top:
            return 0
        return (right - left) * (bottom - top)

    def coverage(self, rect: Rect) -> float:
        """Fraction of *rect* that sits on this monitor (0.0 - 1.0)."""
        rx, ry, rw, rh = rect
        window_area = max(1, rw) * max(1, rh)
        return self.intersection_area(rect) / window_area

    # --- coordinate conversion ---------------------------------------
    def to_global(self, local_x: float, local_y: float, *, frame_size: Optional[Tuple[int, int]] = None) -> Tuple[int, int]:
        """Map a point on a captured bitmap to global screen coordinates.

        When *frame_size* is given (the bitmap's real pixel size) the point is
        first scaled back to the monitor's logical size, which is what makes
        HiDPI captures click accurately.
        """
        scale_x = 1.0
        scale_y = 1.0
        if frame_size and frame_size[0] > 0 and frame_size[1] > 0:
            scale_x = self.width / float(frame_size[0])
            scale_y = self.height / float(frame_size[1])
        gx = self.x + local_x * scale_x
        gy = self.y + local_y * scale_y
        return int(round(gx)), int(round(gy))

    def to_local(self, global_x: float, global_y: float, *, frame_size: Optional[Tuple[int, int]] = None) -> Tuple[int, int]:
        """Inverse of :meth:`to_global` (global screen point -> bitmap pixel)."""
        scale_x = 1.0
        scale_y = 1.0
        if frame_size and frame_size[0] > 0 and frame_size[1] > 0:
            scale_x = frame_size[0] / float(self.width)
            scale_y = frame_size[1] / float(self.height)
        return int(round((global_x - self.x) * scale_x)), int(round((global_y - self.y) * scale_y))

    def clamp_global(self, px: int, py: int) -> Tuple[int, int]:
        """Keep a point inside this monitor (models love clicking at 9999,9999)."""
        return (
            min(max(px, self.x + 1), self.right - 2),
            min(max(py, self.y + 1), self.bottom - 2),
        )

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "scale": self.scale,
            "primary": self.is_primary,
        }


# --- enumeration ------------------------------------------------------------

def _monitors_from_qt() -> List[Monitor]:
    """Enumerate displays with Qt (the same geometry Qt itself uses for windows).

    Uses :func:`naveed.lazy.optional`, not ``load``: Qt being *unimportable*
    (missing system library, no display) is a normal state that must fall through
    to the mss backend rather than raising out of a coordinate conversion.
    """
    QtGui = lazy.optional("PySide6.QtGui")
    if QtGui is None:
        return []
    app = QtGui.QGuiApplication.instance()
    if app is None:
        # Instance() is None when no QGuiApplication exists yet; creating one here
        # would fight the overlay's own app object, so report no monitors and let
        # the caller fall back to mss.
        return []
    primary = QtGui.QGuiApplication.primaryScreen()
    monitors: List[Monitor] = []
    for index, screen in enumerate(QtGui.QGuiApplication.screens()):
        geometry = screen.geometry()
        monitors.append(
            Monitor(
                index=index,
                x=int(geometry.x()),
                y=int(geometry.y()),
                width=int(geometry.width()),
                height=int(geometry.height()),
                scale=float(screen.devicePixelRatio() or 1.0),
                name=str(screen.name() or f"display-{index + 1}"),
                is_primary=bool(primary is not None and screen is primary),
            )
        )
    return monitors


def _monitors_from_mss() -> List[Monitor]:
    """Enumerate displays without Qt, using mss (works on X11/Windows/macOS)."""
    mss = lazy.optional("mss")
    if mss is None:
        return []
    monitors: List[Monitor] = []
    try:
        with mss.mss() as handle:
            for index, entry in enumerate(handle.monitors):
                # mss.monitors[0] is the union of all displays, not a real monitor.
                if index == 0:
                    continue
                monitors.append(
                    Monitor(
                        index=len(monitors),
                        x=int(entry["left"]),
                        y=int(entry["top"]),
                        width=int(entry["width"]),
                        height=int(entry["height"]),
                        scale=1.0,
                        name=f"display-{len(monitors) + 1}",
                        is_primary=len(monitors) == 0,
                    )
                )
    except Exception:
        return []
    return monitors


def list_monitors(*, prefer: str = "qt") -> List[Monitor]:
    """All displays in the virtual desktop.

    Qt is preferred because its coordinates are exactly the ones the overlay
    window and mouse input use; mss is the fallback for headless/watcher-only
    runs.  A single synthetic 1x1 monitor keeps callers from crashing when
    enumeration fails entirely.
    """
    order = ("qt", "mss") if prefer == "qt" else ("mss", "qt")
    for backend in order:
        try:
            monitors = _monitors_from_qt() if backend == "qt" else _monitors_from_mss()
        except Exception:
            # A backend that cannot even enumerate (no display, half-installed
            # toolkit) must never break coordinate maths further up the stack.
            continue
        if monitors:
            return monitors
    return []


def monitors_or_default() -> List[Monitor]:
    """Monitor list that is never empty (falls back to a sane primary)."""
    monitors = list_monitors()
    if monitors:
        return monitors
    return [Monitor(index=0, x=0, y=0, width=1920, height=1080, scale=1.0, name="primary", is_primary=True)]


def primary_monitor(monitors: Optional[Sequence[Monitor]] = None) -> Monitor:
    """The OS-designated primary display, or the first one."""
    monitors = list(monitors or monitors_or_default())
    for monitor in monitors:
        if monitor.is_primary:
            return monitor
    return monitors[0]


def monitor_for_rect(rect: Rect, monitors: Optional[Sequence[Monitor]] = None) -> Monitor:
    """Monitor showing the largest part of *rect* (window-aware capture)."""
    monitors = list(monitors or monitors_or_default())
    return max(monitors, key=lambda monitor: (monitor.intersection_area(rect), monitor.area))


def monitor_at_point(x: int, y: int, monitors: Optional[Sequence[Monitor]] = None) -> Monitor:
    """Monitor containing the point, else the nearest one by centre distance."""
    monitors = list(monitors or monitors_or_default())
    for monitor in monitors:
        if monitor.contains_point(x, y):
            return monitor
    return min(
        monitors,
        key=lambda monitor: (monitor.center[0] - x) ** 2 + (monitor.center[1] - y) ** 2,
    )


def virtual_desktop(monitors: Optional[Sequence[Monitor]] = None) -> Rect:
    """Bounding rect of every display (the full virtual desktop)."""
    monitors = list(monitors or monitors_or_default())
    xs = [monitor.x for monitor in monitors]
    ys = [monitor.y for monitor in monitors]
    rights = [monitor.right for monitor in monitors]
    bottoms = [monitor.bottom for monitor in monitors]
    left, top = min(xs), min(ys)
    return (left, top, max(rights) - left, max(bottoms) - top)
