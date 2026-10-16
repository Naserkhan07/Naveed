"""Vector icons, drawn with the shared canvas so they work on every platform.

Emoji and symbol fonts are not dependable: ``⌂``, ``⚙`` and especially ``🔊``
render as empty boxes on a minimal Linux desktop or a Windows box without the
Segoe UI Symbol variant, and an assistant with broken icons in its header looks
unfinished.  These five icons are therefore drawn from primitives:

``home``      a roof and a body
``add``       a plus
``settings``  a gear (circle, teeth, hub)
``speaker``   a cone with two sound arcs, plus a slash when muted
``close``     an X
``mic``       a hand microphone (used by the Listen button)
``stop``      a rounded square

The same functions paint into :class:`naveed.render.qt_canvas.QtCanvas` (used by
the real panel) and :class:`naveed.render.pillow_canvas.PillowCanvas` (used by the
documentation mock), so the icons in the screenshots and the icons on screen come
from one definition.
"""

from __future__ import annotations

import math
from typing import Callable, Dict

from ..render.canvas import Canvas, Color

__all__ = ["ICON_NAMES", "draw_icon"]

ICON_NAMES = ("home", "add", "settings", "speaker", "speaker_muted", "close", "mic", "stop", "send", "screen")


def _home(canvas: Canvas, x: float, y: float, s: float, color: Color) -> None:
    canvas.polygon(
        [(x + s * 0.5, y + s * 0.12), (x + s * 0.90, y + s * 0.48), (x + s * 0.10, y + s * 0.48)],
        fill=color,
    )
    canvas.rect(x + s * 0.22, y + s * 0.46, s * 0.56, s * 0.42, radius=s * 0.08, fill=color)


def _add(canvas: Canvas, x: float, y: float, s: float, color: Color) -> None:
    width = max(1.6, s * 0.11)
    canvas.line(x + s * 0.5, y + s * 0.18, x + s * 0.5, y + s * 0.82, color=color, width=width)
    canvas.line(x + s * 0.18, y + s * 0.5, x + s * 0.82, y + s * 0.5, color=color, width=width)


def _settings(canvas: Canvas, x: float, y: float, s: float, color: Color) -> None:
    """A gear.

    Built as teeth + a stroked ring, not as "a disc with a hole punched in it":
    compositing a transparent shape over an opaque one is a no-op on both
    back-ends, so an erase step would silently leave a solid blob.  Drawing a
    ring instead keeps the icon identical on Qt and Pillow.
    """
    centre_x, centre_y = x + s * 0.5, y + s * 0.5
    body = s * 0.30
    for index in range(8):
        angle = index * math.pi / 4.0
        canvas.circle(centre_x + math.cos(angle) * body * 0.92, centre_y + math.sin(angle) * body * 0.92, s * 0.10, fill=color)
    canvas.circle(centre_x, centre_y, body, outline=color, outline_width=max(1.8, s * 0.09))
    canvas.circle(centre_x, centre_y, s * 0.075, fill=color)


def _speaker(canvas: Canvas, x: float, y: float, s: float, color: Color, *, muted: bool = False) -> None:
    canvas.polygon(
        [
            (x + s * 0.16, y + s * 0.38),
            (x + s * 0.36, y + s * 0.38),
            (x + s * 0.58, y + s * 0.18),
            (x + s * 0.58, y + s * 0.82),
            (x + s * 0.36, y + s * 0.62),
            (x + s * 0.16, y + s * 0.62),
        ],
        fill=color,
    )
    width = max(1.4, s * 0.075)
    for index, radius in enumerate((0.20, 0.34)):
        steps = 10
        previous = None
        for step in range(steps + 1):
            angle = -math.pi * 0.32 + (math.pi * 0.64) * (step / steps)
            point = (x + s * 0.60 + math.cos(angle) * s * radius, y + s * 0.5 + math.sin(angle) * s * radius)
            if previous is not None:
                canvas.line(previous[0], previous[1], point[0], point[1], color=color, width=width)
            previous = point
    if muted:
        canvas.line(x + s * 0.22, y + s * 0.24, x + s * 0.80, y + s * 0.76, color=color, width=max(1.8, s * 0.10))


def _close(canvas: Canvas, x: float, y: float, s: float, color: Color) -> None:
    width = max(1.6, s * 0.11)
    canvas.line(x + s * 0.26, y + s * 0.26, x + s * 0.74, y + s * 0.74, color=color, width=width)
    canvas.line(x + s * 0.74, y + s * 0.26, x + s * 0.26, y + s * 0.74, color=color, width=width)


def _mic(canvas: Canvas, x: float, y: float, s: float, color: Color) -> None:
    canvas.rect(x + s * 0.36, y + s * 0.14, s * 0.28, s * 0.44, radius=s * 0.14, fill=color)
    canvas.line(x + s * 0.5, y + s * 0.58, x + s * 0.5, y + s * 0.84, color=color, width=max(1.6, s * 0.09))
    canvas.line(x + s * 0.32, y + s * 0.84, x + s * 0.68, y + s * 0.84, color=color, width=max(1.6, s * 0.09))
    # The pickup arc.
    steps = 12
    previous = None
    for step in range(steps + 1):
        angle = math.pi * 0.16 + math.pi * 0.68 * (step / steps)
        point = (x + s * 0.5 + math.cos(angle) * s * 0.26, y + s * 0.44 + math.sin(angle) * s * 0.26)
        if previous is not None:
            canvas.line(previous[0], previous[1], point[0], point[1], color=color, width=max(1.4, s * 0.075))
        previous = point


def _stop(canvas: Canvas, x: float, y: float, s: float, color: Color) -> None:
    canvas.rect(x + s * 0.28, y + s * 0.28, s * 0.44, s * 0.44, radius=s * 0.08, fill=color)


def _send(canvas: Canvas, x: float, y: float, s: float, color: Color) -> None:
    """A paper-plane style arrow pointing right, with a notch cut by the panel."""
    canvas.polygon(
        [(x + s * 0.14, y + s * 0.18), (x + s * 0.88, y + s * 0.5), (x + s * 0.14, y + s * 0.82)],
        fill=color,
    )
    canvas.polygon(
        [(x + s * 0.20, y + s * 0.44), (x + s * 0.56, y + s * 0.5), (x + s * 0.20, y + s * 0.56)],
        fill=(0, 0, 0, 0),
    )


def _screen(canvas: Canvas, x: float, y: float, s: float, color: Color) -> None:
    canvas.rect(x + s * 0.12, y + s * 0.18, s * 0.76, s * 0.5, radius=s * 0.08, fill=color)
    canvas.rect(x + s * 0.44, y + s * 0.68, s * 0.12, s * 0.14, fill=color)
    canvas.rect(x + s * 0.28, y + s * 0.82, s * 0.44, s * 0.08, radius=s * 0.04, fill=color)


_PAINTERS: Dict[str, Callable[..., None]] = {
    "home": _home,
    "add": _add,
    "settings": _settings,
    "speaker": _speaker,
    "speaker_muted": lambda canvas, x, y, s, color: _speaker(canvas, x, y, s, color, muted=True),
    "close": _close,
    "mic": _mic,
    "stop": _stop,
    "send": _send,
    "screen": _screen,
}


def draw_icon(canvas: Canvas, name: str, x: float, y: float, size: float, color: Color = "#C7CEDD") -> None:
    """Draw icon *name* into the box ``(x, y, size, size)``.

    Unknown names draw nothing rather than raising: a missing icon must never be
    able to break painting.
    """
    painter = _PAINTERS.get(name)
    if painter is None:
        return
    painter(canvas, x, y, size, color)
