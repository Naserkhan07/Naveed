"""System-tray icon: the "hide the mascot but keep Naveed alive" surface.

The icon is painted from the same mascot geometry as everything else (so it
always matches the character, at 16px or 64px), and the menu mirrors the panel's
most useful actions.  On platforms without a tray the constructor raises and the
overlay carries on — a missing tray must never stop the companion.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .. import lazy
from ..config import Config
from .mascot import paint_mascot

logger = logging.getLogger("naveed.tray")

__all__ = ["TrayIcon"]


class TrayIcon:
    """Factory + façade for the tray icon."""

    def __init__(
        self,
        config: Config,
        *,
        on_toggle_panel: Optional[Callable[[], None]] = None,
        on_listen: Optional[Callable[[], None]] = None,
        on_look: Optional[Callable[[], None]] = None,
        on_screenshot: Optional[Callable[[], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ) -> None:
        self.config = config
        self.on_toggle_panel = on_toggle_panel
        self.on_listen = on_listen
        self.on_look = on_look
        self.on_screenshot = on_screenshot
        self.on_settings = on_settings
        self.on_quit = on_quit
        self.icon: Any = None

    def build(self) -> Any:
        """Create the tray icon (requires a running QApplication)."""
        QtGui = lazy.load("PySide6.QtGui", extra="ui")
        QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")

        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError("this desktop does not provide a system tray")

        icon = QtWidgets.QSystemTrayIcon(self._pixmap(QtGui), None)
        icon.setToolTip("Naveed — click the mascot to talk")
        menu = QtWidgets.QMenu()

        def add(label: str, callback: Optional[Callable[[], None]]) -> None:
            action = menu.addAction(label)
            if callback is not None:
                action.triggered.connect(lambda: _safe(callback))

        add("Talk to Naveed", self.on_listen)
        add("Show / hide control panel", self.on_toggle_panel)
        menu.addSeparator()
        add("What is on my screen?", self.on_look)
        add("Take a screenshot", self.on_screenshot)
        add("Settings…", self.on_settings)
        menu.addSeparator()
        add("Quit Naveed", self.on_quit)

        icon.setContextMenu(menu)
        icon.activated.connect(self._on_activated)
        self.menu = menu
        self.icon = icon
        return icon

    def _pixmap(self, QtGui) -> Any:
        """Paint the mascot into a QPixmap for the tray icon."""
        from ..render.qt_canvas import QtCanvas

        size = 64
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtGui.QColor(0, 0, 0, 0))
        painter = QtGui.QPainter(pixmap)
        try:
            canvas = QtCanvas(painter, size, size)
            paint_mascot(canvas, 3, 3, size - 6, state="idle", blink=1.0, shadow=False, glow=False)
        finally:
            painter.end()
        return QtGui.QIcon(pixmap)

    def _on_activated(self, reason) -> None:
        QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger and self.on_toggle_panel is not None:
            _safe(self.on_toggle_panel)

    # --- passthroughs -----------------------------------------------------
    def show(self) -> None:
        if self.icon is not None:
            self.icon.show()

    def hide(self) -> None:
        if self.icon is not None:
            self.icon.hide()

    def message(self, title: str, body: str, *, seconds: float = 4.0) -> None:
        """Show a tray balloon (used for things that happen while hidden)."""
        if self.icon is None:
            return
        try:
            self.icon.showMessage(title, body, self.icon.MessageIcon.Information, int(seconds * 1000))
        except Exception:
            pass


def _safe(callback: Callable[[], None]) -> None:
    try:
        callback()
    except Exception:
        logger.debug("tray action failed", exc_info=True)
