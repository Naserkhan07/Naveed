"""A tiny 2-D drawing surface with two implementations.

Why this exists
---------------
Naveed's mascot is drawn, not shipped as a sprite sheet: a procedural mascot can
blink, float, squash, open its mouth while speaking and change expression without
a single artist asset, and stays crisp at every DPI.

Drawing that character directly with ``QPainter`` would make it visible only on a
machine with a working GUI toolkit — impossible to unit-test, impossible to
render in CI, impossible to preview on a headless box.  So the character's
*geometry* (:mod:`naveed.overlay.mascot`) is written once against the
:class:`Canvas` protocol below, and two thin back-ends implement it:

``PillowCanvas``
    Renders to an RGBA image.  Used for headless previews, documentation, tests.
``QtCanvas``
    Renders into a ``QPainter`` on the transparent always-on-top window.

Colours are accepted as ``"#rgb"``, ``"#rrggbb"``, ``"#rrggbbaa"``, ``"r,g,b"``
or ``(r, g, b[, a])`` and normalised once by :func:`parse_color`.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple, Union

__all__ = [
    "Canvas",
    "Color",
    "GradientStops",
    "TRANSPARENT",
    "parse_color",
    "rgba",
    "with_alpha",
]

RGBA = Tuple[int, int, int, int]
Color = Union[str, Sequence[float], RGBA]
GradientStops = Sequence[Tuple[float, Color]]
TRANSPARENT: RGBA = (0, 0, 0, 0)

_NAMED = {
    "transparent": (0, 0, 0, 0),
    "black": (0, 0, 0, 255),
    "white": (255, 255, 255, 255),
    "none": (0, 0, 0, 0),
}


def _clamp(value: float) -> int:
    return 0 if value < 0 else (255 if value > 255 else int(round(value)))


def parse_color(color: Optional[Color], *, default: Optional[RGBA] = None) -> Optional[RGBA]:
    """Normalise any accepted colour form to ``(r, g, b, a)``."""
    if color is None:
        return default
    if isinstance(color, str):
        text = color.strip().lower()
        if text in _NAMED:
            return _NAMED[text]
        if text.startswith("#"):
            digits = text[1:]
            if len(digits) == 3:
                digits = "".join(channel * 2 for channel in digits)
            if len(digits) == 6:
                digits += "ff"
            if len(digits) == 8:
                return (
                    int(digits[0:2], 16),
                    int(digits[2:4], 16),
                    int(digits[4:6], 16),
                    int(digits[6:8], 16),
                )
            raise ValueError(f"unsupported hex colour: {color!r}")
        if "," in text:
            return rgba(*[float(part) for part in text.split(",")])
        raise ValueError(f"unsupported colour: {color!r}")
    if isinstance(color, (tuple, list)):
        return rgba(*color)
    raise ValueError(f"unsupported colour: {color!r}")


def rgba(r: float, g: float, b: float, a: float = 255) -> RGBA:
    """Build an RGBA tuple with clamping; floats in 0-1 are scaled up."""
    if isinstance(r, float) and isinstance(g, float) and isinstance(b, float) and max(r, g, b) <= 1.0:
        r, g, b = r * 255, g * 255, b * 255
    if isinstance(a, float) and a <= 1.0:
        a = a * 255
    return (_clamp(r), _clamp(g), _clamp(b), _clamp(a))


def with_alpha(color: Color, alpha: float) -> RGBA:
    """Return *color* with its alpha replaced (``alpha`` in 0.0-1.0)."""
    resolved = parse_color(color) or (0, 0, 0, 255)
    if alpha <= 1.0:
        alpha = alpha * 255
    return (resolved[0], resolved[1], resolved[2], _clamp(alpha))


class Canvas:
    """The drawing surface contract shared by the Qt and Pillow renderers.

    Coordinates are pixels from the top-left corner, y pointing down.  Shapes
    that run off the edge are clipped by the implementation rather than raising,
    because animation constantly walks shapes past the widget border.
    """

    width: int = 0
    height: int = 0

    # --- primitives ---------------------------------------------------
    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        radius: float = 0,
        fill: Optional[Color] = None,
        outline: Optional[Color] = None,
        outline_width: float = 1,
    ) -> None:
        raise NotImplementedError

    def ellipse(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: Optional[Color] = None,
        outline: Optional[Color] = None,
        outline_width: float = 1,
    ) -> None:
        self.rect(x, y, w, h, radius=min(w, h) / 2.0, fill=fill, outline=outline, outline_width=outline_width)

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        *,
        fill: Optional[Color] = None,
        outline: Optional[Color] = None,
        outline_width: float = 1,
    ) -> None:
        self.ellipse(cx - r, cy - r, r * 2, r * 2, fill=fill, outline=outline, outline_width=outline_width)

    def polygon(
        self,
        points: Iterable[Tuple[float, float]],
        *,
        fill: Optional[Color] = None,
        outline: Optional[Color] = None,
        outline_width: float = 1,
    ) -> None:
        raise NotImplementedError

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        color: Color,
        width: float = 1,
        cap: str = "round",
    ) -> None:
        raise NotImplementedError

    def gradient(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        stops: GradientStops,
        *,
        radius: float = 0,
        direction: str = "vertical",
    ) -> None:
        """Fill a (optionally rounded) rectangle with a linear gradient."""
        raise NotImplementedError

    def radial(self, cx: float, cy: float, radius: float, stops: GradientStops) -> None:
        """Fill a circle with a radial gradient (soft blush, glow, shadow)."""
        raise NotImplementedError

    def blur_region(self, x: float, y: float, w: float, h: float, amount: float) -> None:
        """Blur what has already been drawn inside the rectangle."""
        return None

    # --- text ---------------------------------------------------------
    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        size: float = 13,
        color: Color = "#ffffff",
        weight: str = "regular",
        anchor: str = "lt",
        family: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    def measure(
        self,
        content: str,
        *,
        size: float = 13,
        weight: str = "regular",
        family: Optional[str] = None,
    ) -> Tuple[float, float]:
        raise NotImplementedError

    # --- output -------------------------------------------------------
    def save(self, path: str) -> str:
        raise NotImplementedError
