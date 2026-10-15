"""Colours, geometry and copy for the companion.

The palette and the layout constants live in one file so the Qt widgets, the
Pillow preview and the documentation all describe the *same* mascot and the same
glass panel.  Every number here is expressed so the mascot can be painted at any
size: ``paint_mascot`` multiplies these by the body size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

__all__ = [
    "PALETTE",
    "MASCOT",
    "PANEL",
    "SHORTCUTS",
    "QUICK_ACTIONS",
    "STATUS_TEXT",
    "state_color",
]

# --- palette ---------------------------------------------------------------

PALETTE: Dict[str, str] = {
    # mascot
    "orange": "#FF8A2B",
    "coral": "#FF5B57",
    "coral_deep": "#F24B62",
    "cloud": "#FFFFFF",
    "cloud_base": "#F7FAFF",
    "cloud_shade": "#E4EBF7",
    "cloud_deep": "#D7DFEC",
    "ink": "#15161C",
    "pink": "#FF6B81",
    "pink_deep": "#E14C63",
    "blush": "#FF9EB0",
    # panel glass
    "glass": "#101219",
    "glass_soft": "#191C25",
    "glass_border": "#FFFFFF16",
    "glass_highlight": "#FFFFFF0C",
    "panel_text": "#F4F6FB",
    "panel_muted": "#9AA3B5",
    "panel_faint": "#5C6577",
    # states
    "listening": "#4ADE80",
    "thinking": "#7DD3FC",
    "speaking": "#FFB020",
    "acting": "#A78BFA",
    "success": "#34D399",
    "error": "#FF5A5F",
    "sleeping": "#64748B",
    "connected": "#4ADE80",
    "offline": "#F97316",
}


def state_color(state: str) -> str:
    """Accent colour used for the mascot glow, the status dot and the rings."""
    return PALETTE.get(state, PALETTE["orange"])


# --- mascot geometry (all values are fractions of the body size) -----------

@dataclass(frozen=True)
class MascotMetrics:
    """Proportions of the character, measured off the reference sheet.

    All values are fractions of the paint box, so the identical character can be
    painted at 64px in the tray or 320px on a 4K desktop.
    """

    body_radius: float = 0.295      # rounded-square corner radius
    body_inset: float = 0.02        # transparent breathing room around the body
    # gradient stops of the orange -> coral upper half
    gradient_mid: float = 0.40
    gradient_coral: float = 0.62
    # white cloud face
    cloud_base_top: float = 0.575   # shaded underside starts here
    cloud_top: float = 0.398        # where the white mass begins
    cloud_bottom: float = 0.845     # before the wavy underside bumps
    cloud_radius: float = 0.300
    scallop_count: int = 5
    scallop_y: float = 0.402
    scallop_radius: float = 0.064
    scallop_edge_scale: float = 0.80  # end scallops are smaller than the middle
    bump_count: int = 4
    bump_y: float = 0.782
    bump_radius: float = 0.058
    # face
    eye_radius: float = 0.072
    eye_dx: float = 0.158
    eye_y: float = 0.552
    eye_highlight: float = 0.023
    mouth_y: float = 0.638
    mouth_w: float = 0.080
    mouth_h: float = 0.050
    blush_radius: float = 0.060
    blush_dx: float = 0.240
    blush_y: float = 0.590
    # decorations
    glow_radius: float = 0.640
    ring_radius: float = 0.560


MASCOT = MascotMetrics()

# --- control panel ---------------------------------------------------------

@dataclass(frozen=True)
class PanelMetrics:
    """Compact, horizontal, dark glass panel that floats above the mascot."""

    width: int = 536
    height: int = 246
    radius: int = 22
    padding: int = 14
    header_height: int = 26
    status_card_width: int = 178
    grid_columns: int = 4
    grid_rows: int = 2
    button_height: int = 42
    gap: int = 10
    input_height: int = 38
    opacity: float = 0.80


PANEL = PanelMetrics()

#: Colourful shortcut grid on the right of the panel (label, accent colour).
SHORTCUTS: List[Tuple[str, str]] = [
    ("Look at screen", "#FF8A2B"),
    ("Summarise", "#7DD3FC"),
    ("Screenshot", "#A78BFA"),
    ("Explain error", "#FF5A5F"),
    ("Write for me", "#34D399"),
    ("Clean up", "#FBBF24"),
    ("Translate", "#60A5FA"),
    ("Automate", "#F472B6"),
]

#: Quick actions inside the status card on the left.
QUICK_ACTIONS: List[Tuple[str, str]] = [
    ("Listen", "listening"),
    ("Stop", "error"),
]

STATUS_TEXT: Dict[str, str] = {
    "connected": "Connected",
    "offline": "Offline — no key",
    "watching": "Watching your screen",
    "idle": "Ready when you are",
}
