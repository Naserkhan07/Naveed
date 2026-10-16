"""The visible companion: the floating mascot, the glass panel and the tray."""

from __future__ import annotations

from ..lazy import lazy_attrs

__all__ = ["ControlPanel", "MascotWindow", "OverlayApp", "TrayIcon", "paint_mascot"]

__getattr__ = lazy_attrs(
    globals(),
    {
        "mascot": "naveed.overlay.mascot",
        "paint_mascot": "naveed.overlay.mascot:paint_mascot",
        "MascotAnimator": "naveed.overlay.mascot:MascotAnimator",
        "theme": "naveed.overlay.theme",
        "window": "naveed.overlay.window",
        "MascotWindow": "naveed.overlay.window:MascotWindow",
        "panel": "naveed.overlay.panel",
        "ControlPanel": "naveed.overlay.panel:ControlPanel",
        "tray": "naveed.overlay.tray",
        "TrayIcon": "naveed.overlay.tray:TrayIcon",
        "hotkeys": "naveed.overlay.hotkeys",
        "HotkeyManager": "naveed.overlay.hotkeys:HotkeyManager",
        "bridge": "naveed.overlay.bridge",
        "OverlayApp": "naveed.overlay.bridge:OverlayApp",
    },
)
