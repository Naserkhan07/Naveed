"""Pillow implementation of :class:`naveed.render.canvas.Canvas`.

Used for headless rendering: ``python -m naveed --portrait``, the preview
generator in :mod:`naveed.render.preview`, and the visual regression tests.  It
is deliberately dependency-light (Pillow only) so it works in CI and on machines
that cannot start a GUI toolkit at all.

Two Pillow details shape this file:

* ``ImageDraw`` *replaces* pixels instead of blending them, so every semi
  transparent shape is drawn onto a scratch layer and composited with
  :meth:`PIL.Image.Image.alpha_composite`.  Without the layer, a 30 %-opacity
  blush would punch a hole in the face instead of tinting it.
* Linear gradients are built as a tiny strip and resized with bilinear
  filtering, which is both faster and smoother than per-pixel maths in Python.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, Optional, Sequence, Tuple

from .. import lazy
from .canvas import Canvas, Color, GradientStops, parse_color

__all__ = ["PillowCanvas", "find_font"]

# Common system font locations, in preference order, per platform.
_FONT_CANDIDATES = {
    "regular": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ),
    "bold": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
}


def find_font(weight: str = "regular", family: Optional[str] = None) -> Optional[str]:
    """Locate a TrueType font file, or ``None`` to fall back to Pillow's own."""
    if family:
        for directory in (
            "/usr/share/fonts/truetype",
            "C:/Windows/Fonts",
            "/System/Library/Fonts/Supplemental",
            os.path.expanduser("~/.fonts"),
        ):
            if not os.path.isdir(directory):
                continue
            for root, _dirs, files in os.walk(directory):
                for name in files:
                    if name.lower().startswith(family.lower()) and name.lower().endswith((".ttf", ".otf")):
                        return os.path.join(root, name)
    for candidate in _FONT_CANDIDATES.get(weight, _FONT_CANDIDATES["regular"]):
        if os.path.exists(candidate):
            return candidate
    return None


class PillowCanvas(Canvas):
    """Draws onto an RGBA ``PIL.Image``."""

    def __init__(self, width: int, height: int, *, background: Optional[Color] = None, base_image=None) -> None:
        self._image_module = lazy.load("PIL.Image", extra="capture")
        self._draw_module = lazy.load("PIL.ImageDraw", extra="capture")
        self._font_module = lazy.load("PIL.ImageFont", extra="capture")
        self.width = int(width)
        self.height = int(height)
        if base_image is not None:
            self.image = base_image.convert("RGBA")
            self.width, self.height = self.image.size
        else:
            self.image = self._image_module.new("RGBA", (self.width, self.height), parse_color(background) or (0, 0, 0, 0))
        self._fonts: Dict[Tuple[float, str, Optional[str]], object] = {}

    # --- internals ----------------------------------------------------
    def _new_layer(self):
        return self._image_module.new("RGBA", (self.width, self.height), (0, 0, 0, 0))

    def _flush(self, layer) -> None:
        self.image = self._image_module.alpha_composite(self.image, layer)

    @staticmethod
    def _box(x: float, y: float, w: float, h: float) -> Sequence[float]:
        x2 = x + w
        y2 = y + h
        if x2 < x:
            x, x2 = x2, x
        if y2 < y:
            y, y2 = y2, y
        return [x, y, x2, y2]

    def _font(self, size: float, weight: str, family: Optional[str]):
        key = (round(float(size), 1), weight, family)
        cached = self._fonts.get(key)
        if cached is not None:
            return cached
        path = find_font(weight, family)
        font = None
        if path:
            try:
                font = self._font_module.truetype(path, max(6, int(round(size))))
            except OSError:
                font = None
        if font is None:
            try:
                font = self._font_module.load_default(size=max(6, int(round(size))))
            except TypeError:  # Pillow < 10.1 has no size argument
                font = self._font_module.load_default()
        self._fonts[key] = font
        return font

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
        layer = self._new_layer()
        draw = self._draw_module.Draw(layer)
        box = self._box(x, y, w, h)
        if max(w, h) <= 0:
            return
        kwargs = {}
        if fill is not None:
            kwargs["fill"] = parse_color(fill)
        if outline is not None:
            kwargs["outline"] = parse_color(outline)
            kwargs["width"] = max(1, int(round(outline_width)))
        if radius > 0:
            draw.rounded_rectangle(box, radius=max(0, radius), **kwargs)
        else:
            draw.rectangle(box, **kwargs)
        self._flush(layer)

    def polygon(
        self,
        points: Iterable[Tuple[float, float]],
        *,
        fill: Optional[Color] = None,
        outline: Optional[Color] = None,
        outline_width: float = 1,
    ) -> None:
        layer = self._new_layer()
        draw = self._draw_module.Draw(layer)
        coords = [(float(px), float(py)) for px, py in points]
        kwargs = {}
        if fill is not None:
            kwargs["fill"] = parse_color(fill)
        if outline is not None:
            kwargs["outline"] = parse_color(outline)
            kwargs["width"] = max(1, int(round(outline_width)))
        draw.polygon(coords, **kwargs)
        self._flush(layer)

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
        layer = self._new_layer()
        draw = self._draw_module.Draw(layer)
        draw.line([(x1, y1), (x2, y2)], fill=parse_color(color), width=max(1, int(round(width))))
        if cap == "round":
            radius = max(1, int(round(width / 2.0)))
            for cx, cy in ((x1, y1), (x2, y2)):
                draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=parse_color(color))
        self._flush(layer)

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
        w, h = max(1, int(round(w))), max(1, int(round(h)))
        strip = self._gradient_strip(stops, direction)
        layer = strip.resize((w, h), self._image_module.Resampling.BILINEAR) if strip.size != (w, h) else strip
        if radius > 0:
            # Rounded corners must *clip* the gradient, not replace its alpha: a
            # semi-transparent gradient (alpha 0x14 white for a glass highlight)
            # would otherwise come out fully opaque.
            mask = self._image_module.new("L", (w, h), 0)
            self._draw_module.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=max(0, int(round(radius))), fill=255)
            layer = layer.copy()
            ImageChops = lazy.load("PIL.ImageChops", extra="capture")
            layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
        # Paste into position, honouring the layer's own alpha.
        target = self._new_layer()
        target.alpha_composite(layer, (max(0, int(round(x))), max(0, int(round(y)))))
        self._flush(target)

    def _gradient_strip(self, stops: GradientStops, direction: str):
        """A 1-pixel-wide-per-step gradient image, later resized to the rect."""
        steps = 256
        resolved = [(float(offset), parse_color(color) or (0, 0, 0, 255)) for offset, color in stops]
        resolved.sort(key=lambda item: item[0])
        if len(resolved) == 1:
            resolved = [(0.0, resolved[0][1]), (1.0, resolved[0][1])]

        def sample(offset: float) -> Tuple[int, int, int, int]:
            offset = min(max(offset, 0.0), 1.0)
            previous = resolved[0]
            for current in resolved:
                if current[0] >= offset:
                    span = current[0] - previous[0]
                    ratio = 0.0 if span <= 0 else (offset - previous[0]) / span
                    return tuple(  # type: ignore[return-value]
                        int(round(previous[1][index] + (current[1][index] - previous[1][index]) * ratio))
                        for index in range(4)
                    )
                previous = current
            return resolved[-1][1]

        if direction == "diagonal":
            # 2x2 corner colours, upscaled: bilinear filtering does the diagonal.
            strip = self._image_module.new("RGBA", (2, 2))
            for corner, offset in ((0, 0.0), (1, 0.25), (2, 0.6), (3, 1.0)):
                strip.putpixel((corner % 2, corner // 2), sample(offset))
            return strip
        horizontal = direction == "horizontal"
        size = (steps, 1) if horizontal else (1, steps)
        strip = self._image_module.new("RGBA", size)
        for index in range(steps):
            strip.putpixel((index, 0) if horizontal else (0, index), sample(index / (steps - 1.0)))
        return strip

    def radial(self, cx: float, cy: float, radius: float, stops: GradientStops) -> None:
        radius = max(1, int(round(radius)))
        resolved = [(float(offset), parse_color(color) or (0, 0, 0, 0)) for offset, color in stops]
        resolved.sort(key=lambda item: item[0])
        if len(resolved) == 1:
            resolved = [(0.0, resolved[0][1]), (1.0, resolved[0][1])]

        def sample(offset: float):
            offset = min(max(offset, 0.0), 1.0)
            previous = resolved[0]
            for current in resolved:
                if current[0] >= offset:
                    span = current[0] - previous[0]
                    ratio = 0.0 if span <= 0 else (offset - previous[0]) / span
                    return tuple(  # type: ignore[return-value]
                        int(round(previous[1][index] + (current[1][index] - previous[1][index]) * ratio))
                        for index in range(4)
                    )
                previous = current
            return resolved[-1][1]

        layer = self._new_layer()
        draw = self._draw_module.Draw(layer)
        left, top = cx - radius, cy - radius
        # Concentric fill from the outside in: each inner circle paints over the
        # previous one, which produces a smooth radial ramp with cheap draw calls.
        for step in range(radius, 0, -1):
            color = sample(step / float(radius))
            if color[3] == 0:
                continue
            draw.ellipse([left + (radius - step), top + (radius - step), cx + step, cy + step], fill=color)
        self._flush(layer)

    def blur_region(self, x: float, y: float, w: float, h: float, amount: float) -> None:
        if amount <= 0 or w <= 0 or h <= 0:
            return
        ImageFilter = lazy.load("PIL.ImageFilter", extra="capture")
        left = max(0, int(x))
        top = max(0, int(y))
        right = min(self.width, int(x + w))
        bottom = min(self.height, int(y + h))
        if right <= left or bottom <= top:
            return
        region = self.image.crop((left, top, right, bottom))
        blurred = region.filter(ImageFilter.GaussianBlur(amount))
        self.image.paste(blurred, (left, top))

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
        if not content:
            return
        font = self._font(size, weight, family)
        layer = self._new_layer()
        draw = self._draw_module.Draw(layer)
        paint = parse_color(color)
        pillow_anchor = {"lt": "la", "mt": "ma", "rt": "ra", "mm": "mm", "lm": "lm", "rm": "rm"}.get(anchor, "la")
        try:
            draw.text((x, y), content, font=font, fill=paint, anchor=pillow_anchor)
        except (ValueError, TypeError, AttributeError):
            # Bitmap fallback font: emulating anchors by hand.
            width, height = self.measure(content, size=size, weight=weight, family=family)
            dx = 0.0
            dy = 0.0
            if anchor[0] == "m":
                dx -= width / 2
            elif anchor[0] == "r":
                dx -= width
            if anchor[1] == "m":
                dy -= height / 2
            elif anchor[1] == "b":
                dy -= height
            draw.text((x + dx, y + dy), content, font=font, fill=paint)
        self._flush(layer)

    def measure(
        self,
        content: str,
        *,
        size: float = 13,
        weight: str = "regular",
        family: Optional[str] = None,
    ) -> Tuple[float, float]:
        font = self._font(size, weight, family)
        if not content:
            ascent, descent = getattr(font, "getmetrics", lambda: (size, size * 0.25))()
            return (0.0, float(ascent + descent))
        try:
            box = self._draw_module.Draw(self._new_layer()).textbbox((0, 0), content, font=font, anchor="la")
            return (float(box[2] - box[0]), float(box[3] - box[1]))
        except Exception:
            return (float(len(content) * size * 0.55), float(size * 1.2))

    # --- output -------------------------------------------------------
    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.image.save(path)
        return path

    def fit(self, image, x: float, y: float, w: Optional[float] = None, h: Optional[float] = None) -> None:
        """Composite another RGBA image at a position (used for mock desktops)."""
        target = self._new_layer()
        source = image.convert("RGBA")
        if w and h:
            source = source.resize((int(w), int(h)), self._image_module.Resampling.LANCZOS)
        target.alpha_composite(source, (max(0, int(x)), max(0, int(y))))
        self._flush(target)
