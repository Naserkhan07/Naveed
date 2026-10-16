"""Rendering: one mascot geometry, two paint back-ends (Qt and Pillow)."""

from __future__ import annotations


from ..lazy import lazy_attrs
from .canvas import Canvas, parse_color, with_alpha

__all__ = ["Canvas", "PillowCanvas", "QtCanvas", "parse_color", "with_alpha"]

__getattr__ = lazy_attrs(
    globals(),
    {
        "PillowCanvas": "naveed.render.pillow_canvas:PillowCanvas",
        "QtCanvas": "naveed.render.qt_canvas:QtCanvas",
        "preview": "naveed.render.preview",
    },
)
