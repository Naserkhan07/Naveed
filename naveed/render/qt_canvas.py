"""Qt implementation of :class:`naveed.render.canvas.Canvas`.

This is the renderer used by the real overlay: a ``QPainter`` on a frameless,
transparent, always-on-top window.  Only :mod:`naveed.overlay` uses it, and only
after the mascot is already visible, which is why the Qt import lives inside
:meth:`QtCanvas.__init__` rather than at module import time.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

from .. import lazy
from .canvas import Canvas, Color, GradientStops, parse_color

__all__ = ["QtCanvas"]


class QtCanvas(Canvas):
    """Wraps a live ``QPainter``."""

    def __init__(self, painter, width: int, height: int) -> None:
        self.QtCore = lazy.load("PySide6.QtCore", extra="ui")
        self.QtGui = lazy.load("PySide6.QtGui", extra="ui")
        self.painter = painter
        self.width = int(width)
        self.height = int(height)
        painter.setRenderHint(self.QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(self.QtGui.QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(self.QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        self._font_cache = {}

    # --- helpers ------------------------------------------------------
    def _color(self, color: Color):
        r, g, b, a = parse_color(color) or (0, 0, 0, 0)
        return self.QtGui.QColor(r, g, b, a)

    def _brush(self, color: Color):
        return self.QtGui.QBrush(self._color(color))

    def _pen(self, color: Optional[Color], width: float):
        if color is None or width <= 0:
            return self.QtCore.Qt.PenStyle.NoPen
        pen = self.QtGui.QPen(self._color(color))
        pen.setWidthF(float(width))
        pen.setCapStyle(self.QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(self.QtCore.Qt.PenJoinStyle.RoundJoin)
        return pen

    @staticmethod
    def _rect(x: float, y: float, w: float, h: float):
        return float(x), float(y), float(max(0.0, w)), float(max(0.0, h))

    def _path(self, x: float, y: float, w: float, h: float, radius: float):
        path = self.QtGui.QPainterPath()
        if radius > 0:
            path.addRoundedRect(self.QtCore.QRectF(*self._rect(x, y, w, h)), radius, radius)
        else:
            path.addRect(self.QtCore.QRectF(*self._rect(x, y, w, h)))
        return path

    def _gradient_stops(self, gradient, stops: GradientStops):
        for offset, color in stops:
            gradient.setColorAt(min(max(float(offset), 0.0), 1.0), self._color(color))
        return gradient

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
        if w <= 0 or h <= 0:
            return
        # The half-pixel inset keeps rounded edges from clipping against the
        # integer device grid, which otherwise leaves a visible hairline.
        path = self._path(x + 0.5, y + 0.5, max(0.0, w - 1), max(0.0, h - 1), radius)
        painter = self.painter
        if fill is not None:
            painter.setPen(self.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._brush(fill))
            painter.drawPath(path)
        if outline is not None and outline_width > 0:
            painter.setPen(self._pen(outline, outline_width))
            painter.setBrush(self.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def polygon(
        self,
        points: Iterable[Tuple[float, float]],
        *,
        fill: Optional[Color] = None,
        outline: Optional[Color] = None,
        outline_width: float = 1,
    ) -> None:
        polygon = self.QtGui.QPolygonF([self.QtCore.QPointF(float(px), float(py)) for px, py in points])
        painter = self.painter
        painter.setPen(self._pen(outline, outline_width) if outline is not None else self.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._brush(fill) if fill is not None else self.QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPolygon(polygon)

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
        pen = self._pen(color, width)
        if cap == "butt":
            pen.setCapStyle(self.QtCore.Qt.PenCapStyle.FlatCap)
        self.painter.setPen(pen)
        self.painter.drawLine(self.QtCore.QPointF(x1, y1), self.QtCore.QPointF(x2, y2))

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
        if w <= 0 or h <= 0:
            return
        if direction == "horizontal":
            gradient = self.QtGui.QLinearGradient(x, y, x + w, y)
        elif direction == "diagonal":
            gradient = self.QtGui.QLinearGradient(x, y, x + w, y + h)
        else:
            gradient = self.QtGui.QLinearGradient(x, y, x, y + h)
        self._gradient_stops(gradient, stops)
        painter = self.painter
        painter.setPen(self.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self.QtGui.QBrush(gradient))
        painter.drawPath(self._path(x, y, w, h, radius))

    def radial(self, cx: float, cy: float, radius: float, stops: GradientStops) -> None:
        if radius <= 0:
            return
        gradient = self.QtGui.QRadialGradient(self.QtCore.QPointF(cx, cy), float(radius))
        self._gradient_stops(gradient, stops)
        painter = self.painter
        painter.setPen(self.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self.QtGui.QBrush(gradient))
        painter.drawEllipse(self.QtCore.QPointF(cx, cy), float(radius), float(radius))

    # Qt cannot blur a region of a live painter cheaply, and the mascot never
    # needs it: soft edges are painted as radial gradients instead.  The panel's
    # glass effect blurs a one-off backdrop grab in overlay.panel.
    def blur_region(self, x: float, y: float, w: float, h: float, amount: float) -> None:
        return None

    # --- text ---------------------------------------------------------
    def _font(self, size: float, weight: str, family: Optional[str]):
        key = (round(float(size), 1), weight, family)
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        font = self.QtGui.QFont(family) if family else self.QtGui.QFont()
        font.setPixelSize(max(6, int(round(size))))
        font.setWeight(
            self.QtGui.QFont.Weight.DemiBold if weight in ("bold", "demibold") else self.QtGui.QFont.Weight.Normal
        )
        self._font_cache[key] = font
        return font

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
        metrics = self.QtGui.QFontMetricsF(font)
        width, height = self.measure(content, size=size, weight=weight, family=family)
        dx = 0.0
        if anchor[0] == "m":
            dx = -width / 2.0
        elif anchor[0] == "r":
            dx = -width
        baseline = y + metrics.ascent()
        if anchor[1] == "m":
            baseline = y + metrics.ascent() - height / 2.0
        elif anchor[1] == "b":
            baseline = y
        self.painter.setFont(font)
        self.painter.setPen(self._color(color))
        self.painter.drawText(self.QtCore.QPointF(x + dx, baseline), content)

    def measure(
        self,
        content: str,
        *,
        size: float = 13,
        weight: str = "regular",
        family: Optional[str] = None,
    ) -> Tuple[float, float]:
        metrics = self.QtGui.QFontMetricsF(self._font(size, weight, family))
        return (float(metrics.horizontalAdvance(content or "")), float(metrics.height()))
