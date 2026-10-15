"""Where the mascot appears, and where it was left.

A floating companion has one positional decision that matters on every single
start: *where does it turn up?* Slightly below the middle of the screen — the
original default — is fine on a desktop with nothing else running, but it sits in
the worst possible place on a laptop: it lands in the middle of the text you are
reading, and the first thing you do is drag it out of the way.

The default here is therefore **below the camera**: horizontally centred, just
under the webcam bezel at the top of the screen, which is where a small floating
assistant belongs and where it never covers what you are working on. Drag it
somewhere else and that is where it comes back: the position is remembered
between runs.

Everything in this module is a pure function over numbers plus two small file
helpers, so the placement rules are tested without a display.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("naveed.overlay")

__all__ = [
    "anchor_offset",
    "clear_saved_position",
    "load_saved_position",
    "resolve_start_position",
    "save_position",
]

#: Anchors the user can pick in ``OVERLAY_ANCHOR``.
ANCHORS = ("below_camera", "middle", "top", "bottom", "top_left", "top_right", "bottom_right")

#: Space to leave above the mascot for the camera bezel / window chrome, as a
#: fraction of the screen height — a laptop camera sits in the top ~3% of a 1080p
#: panel, so this clears it and the title bar under it.
_CAMERA_MARGIN = 0.035


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def anchor_offset(
    anchor: str,
    *,
    size: int,
    screen_width: int,
    screen_height: int,
    offset_from_middle: float = 0.16,
) -> Tuple[int, int]:
    """Top-left corner for *anchor* on a screen of this size."""
    anchor = (anchor or "below_camera").strip().lower()
    margin = max(8, int(screen_height * _CAMERA_MARGIN))
    centred_x = int(screen_width / 2 - size / 2)
    right_x = int(screen_width - size - margin)
    bottom_y = int(screen_height - size - margin)
    middle_y = int(screen_height / 2 + screen_height * offset_from_middle - size / 2)

    if anchor == "middle":
        return centred_x, middle_y
    if anchor == "top":
        return centred_x, margin
    if anchor == "bottom":
        return centred_x, bottom_y
    if anchor == "top_left":
        return margin, margin
    if anchor == "top_right":
        return right_x, margin
    if anchor == "bottom_right":
        return right_x, bottom_y
    # "below_camera" and anything unrecognised: the friendly default.
    return centred_x, margin


def resolve_start_position(
    overlay: Any,
    *,
    size: int,
    screen_width: int,
    screen_height: int,
    saved: Optional[Tuple[int, int]] = None,
) -> Tuple[int, int]:
    """The mascot's position at startup.

    Order of preference: an explicit ``OVERLAY_X``/``OVERLAY_Y``, then where the
    user last left it, then the configured anchor. Coordinates are clamped so a
    saved position from a monitor that is no longer attached cannot put the
    mascot off-screen (which looks exactly like "it did not start").
    """
    anchor = str(getattr(overlay, "anchor", "below_camera") or "below_camera")
    default_x, default_y = anchor_offset(
        anchor,
        size=size,
        screen_width=screen_width,
        screen_height=screen_height,
        offset_from_middle=float(getattr(overlay, "offset_from_middle", 0.16) or 0.0),
    )
    remembered = bool(getattr(overlay, "remember_position", True))

    if getattr(overlay, "x", None) is not None or getattr(overlay, "y", None) is not None:
        x = overlay.x if overlay.x is not None else default_x
        y = overlay.y if overlay.y is not None else default_y
    elif remembered and saved is not None:
        x, y = saved
    else:
        x, y = default_x, default_y

    # Fully on screen, both ways round: a mascot hanging off the edge is a
    # mascot the user will report as missing. (Dragging it half off is still
    # possible — it is simply brought back next time.)
    return (
        _clamp(x, 0, max(0, screen_width - size)),
        _clamp(y, 0, max(0, screen_height - size)),
    )


# --- remembering where it was left ------------------------------------------

def _state_file(config: Any) -> Path:
    home = getattr(config, "home", "") or ""
    base = Path(home) if home else Path.home() / ".naveed"
    return base / "state" / "overlay.json"


def load_saved_position(config: Any) -> Optional[Tuple[int, int]]:
    """The last position the user dragged the mascot to, if any."""
    if not getattr(getattr(config, "overlay", None), "remember_position", True):
        return None
    path = _state_file(config)
    try:
        payload: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        x, y = int(payload["x"]), int(payload["y"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return x, y


def save_position(config: Any, x: int, y: int) -> bool:
    """Remember a position. Never raises: failing to save must not break a drag."""
    if not getattr(getattr(config, "overlay", None), "remember_position", True):
        return False
    path = _state_file(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"x": int(x), "y": int(y)}), encoding="utf-8")
        return True
    except OSError as error:
        logger.debug("could not remember the mascot position: %s", error)
        return False


def clear_saved_position(config: Any) -> bool:
    """Forget it (used by the panel's "put it back" action and by tests)."""
    try:
        _state_file(config).unlink()
        return True
    except OSError:
        return False
