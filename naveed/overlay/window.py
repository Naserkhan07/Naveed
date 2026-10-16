"""The floating mascot window.

This is the piece that makes Naveed a companion instead of an app: a frameless,
transparent, always-on-top window just big enough for the character, floating
slightly below the middle of the screen while you work in VS Code, a browser or a
terminal.

What it does
------------
* paints the mascot through :class:`naveed.render.qt_canvas.QtCanvas`, so the same
  geometry as the headless preview;
* animates at a fixed frame rate: float, blink, breathing, listening rings,
  thinking dots, mouth movement while speaking;
* **click = talk** (the user's choice), drag = move it anywhere, double-click =
  open the control panel, right-click = menu;
* can turn **click-through** on demand (:meth:`set_click_through`), which is
  essential: while the agent is clicking around your screen, the mascot must not
  be allowed to swallow that click. :meth:`invisible_for_capture` additionally
  asks Windows to exclude the window from screen capture;
* hides itself for the duration of a screenshot (:meth:`hide_for_capture`), so
  the model never sees the mascot and starts clicking on it.

Everything here imports Qt inside the methods, never at module import, so this
file can be read and tested on a machine without a GUI toolkit.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any, Callable, Optional, Tuple

from .. import lazy
from ..config import Config
from ..render.canvas import with_alpha
from .mascot import MascotAnimator, paint_mascot
from .theme import PALETTE

logger = logging.getLogger("naveed.window")

__all__ = ["MascotWindow", "exclude_window_from_capture"]


def exclude_window_from_capture(handle: int) -> bool:
    """Ask Windows to keep this window out of screen captures.

    ``WDA_EXCLUDEFROMCAPTURE`` (0x11) is the Windows 10 2004+ flag that makes a
    window invisible to ``BitBlt``-based capture while remaining visible to the
    user — exactly the behaviour a screen agent needs for its own overlay.  It is
    best-effort: unsupported systems simply return ``False`` and the overlay falls
    back to hiding itself during a grab.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(handle), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


def _hide_from_taskbar(widget) -> bool:
    """Windows-only: keep the overlay out of the taskbar and Alt-Tab list."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        handle = int(widget.winId())
        user32 = ctypes.windll.user32
        getter = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        setter = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        style = getter(handle, GWL_EXSTYLE)
        setter(handle, GWL_EXSTYLE, (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        return True
    except Exception:
        return False


class MascotWindow:
    """A factory + façade around the real ``QWidget``.

    The class is deliberately *not* a ``QWidget`` subclass: constructing it never
    imports Qt, and the widget itself is created lazily in :meth:`build`.  That
    keeps ``import naveed.overlay`` cheap on machines that only want the watcher
    or the CLI.
    """

    def __init__(
        self,
        config: Config,
        *,
        on_click: Optional[Callable[[], None]] = None,
        on_toggle_panel: Optional[Callable[[], None]] = None,
        on_drag: Optional[Callable[[int, int], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
    ) -> None:
        self.config = config
        self.on_click = on_click
        self.on_toggle_panel = on_toggle_panel
        self.on_drag = on_drag
        self.on_command = on_command
        self.on_quit = on_quit
        self.on_settings = on_settings

        self.animator = MascotAnimator()
        self.state = "idle"
        self.microphone_level = 0.0
        self.speech_mouth = 0.0
        self.widget: Any = None
        self._click_through = False
        self._last_tick = time.time()
        self._hidden_for_capture = False
        self._drag_origin: Optional[Tuple[float, float]] = None
        self._drag_moved = False
        self._frame_height = 0.0

    # --- geometry ------------------------------------------------------
    @property
    def size(self) -> int:
        """Width/height of the square overlay window, in logical pixels."""
        return int(self.config.overlay.size + self.config.overlay.padding * 2)

    def default_position(self, screen_width: int = 0, screen_height: int = 0) -> Tuple[int, int]:
        """Where the mascot starts: below the camera, or where it was left.

        See :mod:`naveed.overlay.placement` for the rules; this only supplies the
        screen size and the remembered position.
        """
        from .placement import load_saved_position, resolve_start_position

        screen_width = screen_width or _primary_screen_size()[0]
        screen_height = screen_height or _primary_screen_size()[1]
        return resolve_start_position(
            self.config.overlay,
            size=self.size,
            screen_width=screen_width,
            screen_height=screen_height,
            saved=load_saved_position(self.config),
        )

    # --- lifecycle -----------------------------------------------------
    def build(self) -> Any:
        """Create the Qt widget (imports Qt at this point)."""
        if self.widget is not None:
            return self.widget

        QtCore = lazy.load("PySide6.QtCore", extra="ui")
        QtGui = lazy.load("PySide6.QtGui", extra="ui")
        QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")

        overlay = self.config.overlay
        facade = self

        class _MascotWidget(QtWidgets.QWidget):
            """The actual always-on-top character."""

            def __init__(self) -> None:
                super().__init__(None)
                self.setWindowTitle("Naveed")
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
                self.setWindowFlags(
                    QtCore.Qt.WindowType.FramelessWindowHint
                    | QtCore.Qt.WindowType.Tool
                    | QtCore.Qt.WindowType.WindowStaysOnTopHint
                    | QtCore.Qt.WindowType.NoDropShadowWindowHint
                )
                self.setMouseTracking(True)
                self.setToolTip(
                    "Click to talk · drag to move · double-click for the panel · right-click for more"
                )
                size = facade.size
                self.resize(size, size)
                self._build_menu(QtWidgets, QtGui)

                self.timer = QtCore.QTimer(self)
                self.timer.timeout.connect(self._tick)
                self.timer.start(int(1000 / max(10, overlay.fps)))

            # --- painting ------------------------------------------------
            def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
                QtGuiLocal = lazy.load("PySide6.QtGui", extra="ui")
                from ..render.qt_canvas import QtCanvas

                frame = facade.frame()
                painter = QtGuiLocal.QPainter(self)
                try:
                    canvas = QtCanvas(painter, self.width(), self.height())
                    pad = facade.config.overlay.padding
                    size = facade.config.overlay.size
                    # The float offset is a fraction of the mascot size, so it
                    # reads the same at every scale.
                    paint_mascot(
                        canvas,
                        pad,
                        pad + frame.float_offset * size,
                        size,
                        state=facade.state,
                        blink=frame.blink,
                        mouth=facade._mouth_value(),
                        phase=frame.phase,
                        squash=frame.squash,
                        shadow=True,
                        glow=True,
                    )
                    facade._paint_caption(canvas, pad, size)
                finally:
                    painter.end()

            def _tick(self) -> None:
                now = time.time()
                delta = now - facade._last_tick
                facade._last_tick = now
                frame = facade.animator.update(delta)
                facade._frame = frame
                self.update()

            # --- interaction ---------------------------------------------
            def mousePressEvent(self, event) -> None:  # noqa: N802
                if event.button() == QtCore.Qt.MouseButton.LeftButton:
                    facade._drag_origin = (event.globalPosition().x(), event.globalPosition().y())
                    facade._drag_moved = False
                    event.accept()
                elif event.button() == QtCore.Qt.MouseButton.RightButton:
                    self.menu.popup(event.globalPosition().toPoint())
                    event.accept()

            def mouseMoveEvent(self, event) -> None:  # noqa: N802
                if facade._drag_origin is None:
                    return
                dx = event.globalPosition().x() - facade._drag_origin[0]
                dy = event.globalPosition().y() - facade._drag_origin[1]
                if abs(dx) + abs(dy) > 3:
                    facade._drag_moved = True
                facade._drag_origin = (event.globalPosition().x(), event.globalPosition().y())
                self.move(int(self.x() + dx), int(self.y() + dy))
                if facade.on_drag is not None:
                    facade.on_drag(self.x(), self.y())
                event.accept()

            def mouseReleaseEvent(self, event) -> None:  # noqa: N802
                if event.button() != QtCore.Qt.MouseButton.LeftButton:
                    return
                facade._drag_origin = None
                if facade._drag_moved:
                    # Remember where it was put: the mascot is meant to be dragged
                    # somewhere convenient once, not every single morning.
                    facade.remember_position(self.x(), self.y())
                elif facade.on_click is not None:
                    facade.on_click()
                event.accept()

            def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
                if event.button() == QtCore.Qt.MouseButton.LeftButton and facade.on_toggle_panel is not None:
                    facade.on_toggle_panel()
                    event.accept()

            # --- context menu --------------------------------------------
            def _build_menu(self, QtWidgetsLocal, QtGuiLocal) -> None:
                self.menu = QtWidgetsLocal.QMenu(self)
                actions = (
                    ("Talk to Naveed", lambda: facade.on_click and facade.on_click()),
                    ("Open control panel", lambda: facade.on_toggle_panel and facade.on_toggle_panel()),
                    ("What is on my screen?", lambda: facade.on_command and facade.on_command("what is on my screen?")),
                    ("Take a screenshot", lambda: facade.on_command and facade.on_command("__screenshot__")),
                    ("Settings…", lambda: facade.on_settings and facade.on_settings()),
                    ("Hide for a while", lambda: self.hide()),
                    ("Quit Naveed", lambda: facade.on_quit and facade.on_quit()),
                )
                for label, callback in actions:
                    if label == "Quit Naveed":
                        self.menu.addSeparator()
                    action = self.menu.addAction(label)
                    action.triggered.connect(callback)

        self.widget = _MascotWidget()
        self._frame = self.animator.update(0.0)
        return self.widget

    # --- animation values ----------------------------------------------
    def frame(self):
        """The animation frame currently being painted."""
        frame = getattr(self, "_frame", None)
        if frame is None:
            frame = self.animator.update(0.0)
            self._frame = frame
        return frame

    def _paint_caption(self, canvas, padding: int, size: int) -> None:
        """Draw the transient caption pill under the mascot, if one is active."""
        text = getattr(self, "caption", "")
        if not text or time.time() > getattr(self, "caption_until", 0.0):
            return
        width = min(self.size - 12, max(120.0, canvas.measure(text, size=12.5)[0] + 26))
        left = (self.size - width) / 2.0
        top = padding + size * 1.02
        canvas.rect(left, top, width, 30, radius=15, fill=with_alpha(PALETTE["glass"], 0.88))
        canvas.rect(left, top, width, 30, radius=15, outline=with_alpha(PALETTE["glass_border"], 0.9), outline_width=1)
        canvas.text(left + width / 2.0, top + 15, text[:64], size=12.5, color=PALETTE["panel_text"], anchor="mm")

    def _mouth_value(self) -> float:
        """Mouth openness: speech envelope wins, listening hum is the floor."""
        if self.state == "speaking":
            return max(self.speech_mouth, 0.12)
        if self.state == "listening":
            return 0.1 + 0.25 * self.microphone_level
        return 0.0

    def _squash_value(self) -> float:
        return getattr(self, "_frame").squash if getattr(self, "_frame", None) else 0.0

    # --- state -----------------------------------------------------------
    def set_state(self, state: str) -> None:
        """Change expression (idle, listening, thinking, speaking, acting…)."""
        self.state = state if state in ("idle", "listening", "thinking", "speaking", "acting", "success", "error", "sleeping") else "idle"
        self.animator.set_state(self.state)

    def set_microphone_level(self, level: float) -> None:
        self.microphone_level = max(0.0, min(1.0, float(level)))

    def set_speech_level(self, level: float) -> None:
        """Feed the loudness of the current spoken word (lip-sync)."""
        self.speech_mouth = max(0.0, min(1.0, float(level)))
        self.animator.speak_pulse(self.speech_mouth)

    def celebrate(self) -> None:
        """Flash the success expression (task finished well)."""
        self.set_state("success")

    # --- window operations ------------------------------------------------
    def show(self, *, position: Optional[Tuple[int, int]] = None) -> None:
        widget = self.build()
        x, y = position or self.default_position()
        widget.move(int(x), int(y))
        widget.show()
        widget.raise_()
        if self.config.overlay.always_on_top:
            self.set_always_on_top(True)
        _hide_from_taskbar(widget)
        exclude_window_from_capture(int(widget.winId())) if sys.platform.startswith("win") else None

    def hide(self) -> None:
        if self.widget is not None:
            self.widget.hide()

    def move_to(self, x: int, y: int) -> None:
        if self.widget is not None:
            self.widget.move(int(x), int(y))

    def remember_position(self, x: int, y: int) -> None:
        """Store a dragged position (a no-op unless the setting is on)."""
        from .placement import save_position

        save_position(self.config, x, y)

    def reset_position(self) -> None:
        """Back to the anchor position (the panel's "put it back" action)."""
        from .placement import clear_saved_position

        clear_saved_position(self.config)
        if self.widget is not None:
            x, y = self.default_position()
            self.widget.move(int(x), int(y))

    def position(self) -> Tuple[int, int]:
        if self.widget is None:
            return (0, 0)
        return (self.widget.x(), self.widget.y())

    def set_always_on_top(self, enabled: bool = True) -> None:
        if self.widget is None:
            return
        QtCore = lazy.load("PySide6.QtCore", extra="ui")
        self.widget.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, bool(enabled))
        self.widget.show()  # re-showing is required after a flag change

    def set_click_through(self, enabled: bool = True) -> None:
        """Let clicks pass through to whatever is underneath.

        Used while the agent is driving the mouse: without this, the mascot
        floating in the middle of the screen would eat the agent's own clicks.
        """
        if self.widget is None or enabled == self._click_through:
            return
        QtCore = lazy.load("PySide6.QtCore", extra="ui")
        self.widget.setWindowFlag(QtCore.Qt.WindowType.WindowTransparentForInput, bool(enabled))
        self.widget.show()
        self._click_through = bool(enabled)

    @property
    def click_through(self) -> bool:
        return self._click_through

    # --- capture cooperation ------------------------------------------------
    def hide_for_capture(self) -> None:
        """Temporarily hide (before a screenshot) if we cannot be excluded."""
        if self._hidden_for_capture or self.widget is None:
            return
        try:
            if self.widget.isVisible():
                self.widget.hide()
                self._hidden_for_capture = True
        except Exception:
            pass

    def show_after_capture(self) -> None:
        if not self._hidden_for_capture:
            return
        self._hidden_for_capture = False
        try:
            if self.widget is not None:
                self.widget.show()
                if self.config.overlay.always_on_top:
                    self.widget.raise_()
        except Exception:
            pass

    def toast(self, text: str, *, seconds: float = 4.0) -> None:
        """Painted caption under the mascot (no speech, no panel needed)."""
        self.caption = text
        self.caption_until = time.time() + seconds

    # --- teardown ----------------------------------------------------------
    def close(self) -> None:
        widget = self.widget
        self.widget = None
        if widget is not None:
            try:
                widget.timer.stop()
                widget.close()
                widget.deleteLater()
            except Exception:
                pass


def _primary_screen_size() -> Tuple[int, int]:
    """Screen size from Qt when available, else from the monitor helpers."""
    QtGui = lazy.optional("PySide6.QtGui")
    if QtGui is not None:
        try:
            app = QtGui.QGuiApplication.instance()
            if app is not None:
                screen = QtGui.QGuiApplication.primaryScreen()
                if screen is not None:
                    geometry = screen.geometry()
                    return int(geometry.width()), int(geometry.height())
        except Exception:
            pass
    from ..screen.displays import primary_monitor

    monitor = primary_monitor()
    return monitor.width, monitor.height
