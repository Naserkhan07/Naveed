"""Screen awareness: capture, monitor geometry, change detection, world model.

Everything the companion needs in order to "sit and watch the screen" lives
here, and none of it imports a GUI toolkit unless a GUI is already running.
"""

from __future__ import annotations

from typing import Any, Dict

from ..lazy import lazy_attrs

__all__ = [
    "CaptureError",
    "CaptureService",
    "ChangeDetector",
    "Frame",
    "Monitor",
    "ScreenState",
    "ScreenStateGraph",
    "ScreenWatcher",
    "ScreenshotStore",
    "active_window",
    "list_monitors",
    "monitor_for_rect",
    "primary_monitor",
    "virtual_desktop",
]

# Sub-modules are cheap (stdlib only), so they are imported eagerly; the heavy
# third-party imports inside them stay lazy.
from .capture import CaptureError, CaptureService, Frame  # noqa: E402
from .diff import ChangeDetector  # noqa: E402
from .displays import (  # noqa: E402
    Monitor,
    list_monitors,
    monitor_for_rect,
    primary_monitor,
    virtual_desktop,
)
from .focus import active_window  # noqa: E402
from .retention import ScreenshotStore  # noqa: E402
from .state import ScreenState, ScreenStateGraph  # noqa: E402
from .watch import ScreenWatcher  # noqa: E402

__getattr__ = lazy_attrs(
    globals(),
    {
        "capture_fallback": "naveed.screen.capture_fallback",
        "state": "naveed.screen.state",
        "diff": "naveed.screen.diff",
        "displays": "naveed.screen.displays",
        "focus": "naveed.screen.focus",
        "retention": "naveed.screen.retention",
    },
)


def summary() -> Dict[str, Any]:
    """Human-readable report of what screen awareness can do right now."""
    from .capture import available_backends
    from .capture_fallback import get_screen_access_status

    return {
        "backends": [backend.name for backend in available_backends()],
        "screen_access": get_screen_access_status(),
        "platform": __import__("sys").platform,
    }
