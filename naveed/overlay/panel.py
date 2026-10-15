"""The floating control panel: status card, shortcut grid, chat and settings.

The user's reference describes "a compact, horizontally oriented, dark translucent
control panel with rounded corners", sitting above the mascot, with a small
assistant status card on the left, colourful shortcut buttons in a grid on the
right, and home/add/settings/speaker icons along the top edge.  That is exactly
what this file builds:

::

    ┌──────────────────────────────────────────────────────────────┐
    │  ⌂   Naveed                              ＋   ⚙   🔊          │  header
    ├──────────────────┬───────────────────────────────────────────┤
    │   ◕  Connected   │  [Look]  [Summarise] [Shot]   [Explain]   │  shortcut
    │   watching VS    │  [Write] [Clean up]  [Trans]  [Automate]  │  grid
    │   [Listen][Stop] │                                           │
    ├──────────────────┴───────────────────────────────────────────┤
    │  Ask Naveed anything…                                  ▶      │  input
    ├──────────────────────────────────────────────────────────────┤
    │  ✔ Clicked at 812,404            12:04:11                    │  action log
    └──────────────────────────────────────────────────────────────┘

Everything is styled to match the mascot: dark glass, soft shadows, rounded
corners, the same orange/coral accents, and the same thin borders.  The panel is
a *Tool* window like the mascot: no taskbar entry, always on top, and it never
steals focus from the app you are working in unless you click its input box.

Like :mod:`naveed.overlay.window`, this module imports no Qt at module level and
exposes a factory (:class:`ControlPanel`) plus the real ``QWidget`` inside.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import lazy
from ..config import Config, PROVIDER_PRESETS
from .icons import draw_icon
from .mascot import paint_mascot
from .theme import PALETTE, PANEL, state_color

logger = logging.getLogger("naveed.panel")

__all__ = ["ControlPanel"]


#: Stylesheet for the whole panel.  Kept as one string so the palette stays the
#: single source of truth (it is formatted in with :data:`PALETTE`).
def _stylesheet() -> str:
    palette = PALETTE
    return f"""
    QWidget#NaveedPanel {{
        color: {palette['panel_text']};
        font-family: "Segoe UI", "SF Pro Text", "Inter", "DejaVu Sans", sans-serif;
        font-size: 12px;
    }}
    QLabel#Title {{ font-size: 13px; font-weight: 600; letter-spacing: 0.3px; color: {palette['panel_text']}; }}
    QLabel#Muted {{ color: {palette['panel_muted']}; font-size: 11px; }}
    QLabel#Faint {{ color: {palette['panel_faint']}; font-size: 10.5px; }}
    QLabel#StatusStrong {{ font-size: 12.5px; font-weight: 600; }}
    QFrame#Card, QFrame#Glass {{
        background: rgba(255,255,255,0.045);
        border: 1px solid {palette['glass_border']};
        border-radius: 14px;
    }}
    QFrame#Divider {{ background: {palette['glass_border']}; max-height: 1px; border: none; }}
    QPushButton {{
        background: rgba(255,255,255,0.06);
        border: 1px solid {palette['glass_border']};
        border-radius: 10px;
        padding: 7px 10px;
        color: {palette['panel_text']};
        text-align: left;
    }}
    QPushButton:hover {{ background: rgba(255,255,255,0.12); }}
    QPushButton:pressed {{ background: rgba(255,255,255,0.18); }}
    QPushButton:disabled {{ color: {palette['panel_faint']}; background: rgba(255,255,255,0.03); }}
    QPushButton#Icon {{ padding: 2px; border-radius: 8px; text-align: center; }}
    QPushButton#Icon:hover {{ background: rgba(255,255,255,0.16); }}
    QPushButton#Primary {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {palette['orange']}, stop:1 {palette['coral']});
        border: none; color: #1A1207; font-weight: 600; text-align: center;
    }}
    QPushButton#Danger {{ background: rgba(255,90,95,0.18); border-color: rgba(255,90,95,0.45); text-align: center; }}
    QPushButton#Ghost {{ background: transparent; border: none; color: {palette['panel_muted']}; text-align: left; }}
    QLineEdit {{
        background: rgba(0,0,0,0.28);
        border: 1px solid {palette['glass_border']};
        border-radius: 10px;
        padding: 8px 10px;
        color: {palette['panel_text']};
        selection-background-color: {palette['coral']};
    }}
    QLineEdit:focus {{ border: 1px solid {palette['orange']}; }}
    QComboBox {{
        background: rgba(0,0,0,0.28); border: 1px solid {palette['glass_border']};
        border-radius: 8px; padding: 5px 8px; color: {palette['panel_text']};
    }}
    QCheckBox {{ color: {palette['panel_muted']}; spacing: 8px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.18); border-radius: 3px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


class ControlPanel:
    """Factory + façade for the panel widget."""

    def __init__(
        self,
        config: Config,
        *,
        on_command: Optional[Callable[[str], None]] = None,
        on_quick: Optional[Callable[[str], None]] = None,
        on_listen: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        on_answer: Optional[Callable[[str], None]] = None,
        on_confirm: Optional[Callable[[str, bool], None]] = None,
        on_settings: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_hide: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
        muted: bool = False,
        on_toggle_mute: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self.config = config
        self.on_command = on_command
        self.on_quick = on_quick
        self.on_listen = on_listen
        self.on_stop = on_stop
        self.on_answer = on_answer
        self.on_confirm = on_confirm
        self.on_settings = on_settings
        self.on_hide = on_hide
        self.on_quit = on_quit
        self.on_toggle_mute = on_toggle_mute
        self.muted = muted

        self.widget: Any = None
        self._labels: Dict[str, Any] = {}
        self._buttons: Dict[str, Any] = {}
        self._state: Dict[str, Any] = {}
        self._log_rows: List[Any] = []
        self._question: str = ""
        self._confirm_token: str = ""
        self._settings_open = False

    # --- construction -----------------------------------------------------
    def build(self) -> Any:
        if self.widget is not None:
            return self.widget

        QtCore = lazy.load("PySide6.QtCore", extra="ui")
        QtGui = lazy.load("PySide6.QtGui", extra="ui")
        QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")

        facade = self

        class _Panel(QtWidgets.QWidget):
            """The glass panel itself."""

            def __init__(self) -> None:
                super().__init__(None)
                self.setObjectName("NaveedPanel")
                self.setWindowTitle("Naveed")
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
                self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
                self.setWindowFlags(
                    QtCore.Qt.WindowType.FramelessWindowHint
                    | QtCore.Qt.WindowType.Tool
                    | QtCore.Qt.WindowType.WindowStaysOnTopHint
                    | QtCore.Qt.WindowType.NoDropShadowWindowHint
                )
                self.setStyleSheet(_stylesheet())
                self.resize(PANEL.width, PANEL.height)
                self._drag_origin = None
                self._build_ui(QtCore, QtGui, QtWidgets)

            # --- painting ---------------------------------------------
            def paintEvent(self, event) -> None:  # noqa: N802
                QtGuiLocal = lazy.load("PySide6.QtGui", extra="ui")
                from ..render.qt_canvas import QtCanvas  # local: keeps Qt lazy

                painter = QtGuiLocal.QPainter(self)
                try:
                    canvas = QtCanvas(painter, self.width(), self.height())
                    radius = PANEL.radius
                    # Soft drop shadow behind the glass.
                    canvas.rect(0, 3, self.width(), self.height(), radius=radius, fill="#00000000")
                    for index, alpha in enumerate((26, 34, 44)):
                        canvas.rect(
                            index + 1,
                            3 + index,
                            self.width() - 2 * (index + 1),
                            self.height() - 2,
                            radius=radius - index,
                            fill=f"#000000{alpha:02x}",
                        )
                    canvas.gradient(
                        0,
                        0,
                        self.width(),
                        self.height(),
                        [(0.0, "#1B1F2B"), (0.55, "#141822"), (1.0, "#101319")],
                        radius=radius,
                    )
                    canvas.rect(
                        0,
                        0,
                        self.width(),
                        self.height(),
                        radius=radius,
                        outline=PALETTE["glass_border"],
                        outline_width=1,
                    )
                    # Top highlight: the "glass" cue that sells the material.
                    canvas.gradient(
                        12,
                        1,
                        self.width() - 24,
                        42,
                        [(0.0, "#FFFFFF14"), (1.0, "#FFFFFF00")],
                        radius=12,
                    )
                finally:
                    painter.end()

            # --- dragging the panel ------------------------------------
            def mousePressEvent(self, event) -> None:  # noqa: N802
                if event.button() == QtCore.Qt.MouseButton.LeftButton:
                    self._drag_origin = event.globalPosition().toPoint()

            def mouseMoveEvent(self, event) -> None:  # noqa: N802
                if self._drag_origin is None:
                    return
                delta = event.globalPosition().toPoint() - self._drag_origin
                self.move(self.pos() + delta)
                self._drag_origin = event.globalPosition().toPoint()

            def mouseReleaseEvent(self, event) -> None:  # noqa: N802
                self._drag_origin = None

            # --- UI construction -----------------------------------------
            def _build_ui(self, QtCoreLocal, QtGuiLocal, QtWidgetsLocal) -> None:
                root = QtWidgetsLocal.QVBoxLayout(self)
                root.setContentsMargins(PANEL.padding, PANEL.padding - 4, PANEL.padding, PANEL.padding - 2)
                root.setSpacing(9)

                root.addLayout(self._header(QtWidgetsLocal))
                body = QtWidgetsLocal.QHBoxLayout()
                body.setSpacing(9)
                body.addWidget(self._status_card(QtWidgetsLocal))
                body.addLayout(self._shortcut_grid(QtWidgetsLocal), 1)
                root.addLayout(body)
                root.addWidget(self._divider(QtWidgetsLocal))
                root.addLayout(self._input_row(QtWidgetsLocal))
                root.addWidget(self._log_area(QtWidgetsLocal), 1)

            def _divider(self, QtWidgetsLocal):
                line = QtWidgetsLocal.QFrame()
                line.setObjectName("Divider")
                line.setFixedHeight(1)
                return line

            def _header(self, QtWidgetsLocal):
                row = QtWidgetsLocal.QHBoxLayout()
                row.setSpacing(6)

                title = QtWidgetsLocal.QLabel("Naveed")
                title.setObjectName("Title")
                row.addWidget(title)

                self.status_dot = QtWidgetsLocal.QLabel("●")
                self.status_dot.setStyleSheet(f"color: {state_color('idle')}; font-size: 12px;")
                row.addWidget(self.status_dot)

                facade._labels["header_state"] = QtWidgetsLocal.QLabel("starting…")
                facade._labels["header_state"].setObjectName("Muted")
                row.addWidget(facade._labels["header_state"])
                row.addStretch(1)

                def icon_button(icon: str, tooltip: str, callback) -> Any:
                    button = icon_button_cls(icon)
                    button.setToolTip(tooltip)
                    button.clicked.connect(callback)
                    row.addWidget(button)
                    return button

                icon_button_cls = build_icon_button(QtWidgetsLocal)
                icon_button("home", "Show the mascot and status", lambda: facade._fire("home"))
                icon_button("add", "New question about the screen", lambda: self.command_edit.setFocus())
                facade._buttons["settings"] = icon_button("settings", "Settings", lambda: facade.toggle_settings())
                self.mute_button = _MuteButton(QtWidgetsLocal, facade)
                row.addWidget(self.mute_button)
                icon_button("close", "Hide the panel", lambda: facade.hide())
                return row

            def _status_card(self, QtWidgetsLocal):
                card = QtWidgetsLocal.QFrame()
                card.setObjectName("Card")
                card.setFixedWidth(PANEL.status_card_width)
                layout = QtWidgetsLocal.QVBoxLayout(card)
                layout.setContentsMargins(11, 10, 11, 10)
                layout.setSpacing(6)

                top = QtWidgetsLocal.QHBoxLayout()
                top.setSpacing(8)
                self.mini = build_mini_mascot(card)
                self.mini.setFixedSize(38, 38)
                top.addWidget(self.mini)

                texts = QtWidgets.QVBoxLayout()
                texts.setSpacing(1)
                facade._labels["connection"] = QtWidgets.QLabel("Offline — no key")
                facade._labels["connection"].setObjectName("StatusStrong")
                facade._labels["connection"].setStyleSheet(f"color: {PALETTE['offline']};")
                facade._labels["model"] = QtWidgets.QLabel("no model")
                facade._labels["model"].setObjectName("Faint")
                texts.addWidget(facade._labels["connection"])
                texts.addWidget(facade._labels["model"])
                top.addLayout(texts, 1)
                layout.addLayout(top)

                facade._labels["watching"] = QtWidgets.QLabel("Watching: starting…")
                facade._labels["watching"].setObjectName("Muted")
                facade._labels["watching"].setWordWrap(True)
                layout.addWidget(facade._labels["watching"])

                actions = QtWidgetsLocal.QHBoxLayout()
                actions.setSpacing(6)
                QtGuiLocal = lazy.load("PySide6.QtGui", extra="ui")
                QtCoreLocal = lazy.load("PySide6.QtCore", extra="ui")

                def labelled(icon: str, text: str, object_name: str, tip: str, callback) -> Any:
                    """A button with a *vector* icon and a label.

                    Setting a QIcon from :func:`draw_icon_pixmap` (rather than
                    putting a glyph like "🔊" in the text) is what keeps the
                    buttons legible on a machine with no emoji font.
                    """
                    button = QtWidgetsLocal.QPushButton("  " + text)
                    button.setObjectName(object_name)
                    button.setIcon(QtGuiLocal.QIcon(draw_icon_pixmap(QtGuiLocal, icon, 16, "#1A1207" if object_name == "Primary" else "#FFC9CB")))
                    button.setIconSize(QtCoreLocal.QSize(16, 16))
                    button.setToolTip(tip)
                    button.clicked.connect(callback)
                    return button

                facade._buttons["listen"] = labelled("mic", "Listen", "Primary",
                                                     "Click, then talk — or press the hotkey",
                                                     lambda: facade._fire("listen"))
                facade._buttons["stop"] = labelled("stop", "Stop", "Danger",
                                                   "Cancel the current task",
                                                   lambda: facade._fire("stop"))
                actions.addWidget(facade._buttons["listen"], 1)
                actions.addWidget(facade._buttons["stop"], 1)
                layout.addLayout(actions)

                facade._labels["activity"] = QtWidgets.QLabel("")
                facade._labels["activity"].setObjectName("Faint")
                facade._labels["activity"].setWordWrap(True)
                layout.addWidget(facade._labels["activity"])
                return card

            def _shortcut_grid(self, QtWidgetsLocal):
                grid = QtWidgetsLocal.QGridLayout()
                grid.setSpacing(6)
                keys = [
                    ("look", "Look at screen", "#FF8A2B"),
                    ("summarise", "Summarise", "#7DD3FC"),
                    ("screenshot", "Screenshot", "#A78BFA"),
                    ("explain_error", "Explain error", "#FF5A5F"),
                    ("write", "Write for me", "#34D399"),
                    ("clean_up", "Clean up", "#FBBF24"),
                    ("translate", "Translate", "#60A5FA"),
                    ("automate", "Automate", "#F472B6"),
                ]
                for index, (key, label, accent) in enumerate(keys):
                    button = QtWidgetsLocal.QPushButton(f"●  {label}")
                    button.setStyleSheet(
                        "QPushButton {"
                        f"border-left: 3px solid {accent};"
                        f"color: {PALETTE['panel_text']};"
                        "text-align: left; padding: 7px 8px;"
                        "}"
                        "QPushButton:hover { background: rgba(255,255,255,0.12); }"
                    )
                    button.clicked.connect(lambda _=False, k=key: facade._fire("quick", k))
                    grid.addWidget(button, index // 4, index % 4)
                    facade._buttons[key] = button
                return grid

            def _input_row(self, QtWidgetsLocal):
                row = QtWidgetsLocal.QHBoxLayout()
                row.setSpacing(6)
                self.command_edit = QtWidgetsLocal.QLineEdit()
                self.command_edit.setPlaceholderText("Tell Naveed what to do on this screen…")
                self.command_edit.returnPressed.connect(self._submit_command)
                row.addWidget(self.command_edit, 1)
                self.send_button = build_icon_button(QtWidgetsLocal)("send")
                self.send_button.setObjectName("Primary")
                self.send_button.setFixedSize(40, 34)
                self.send_button.setToolTip("Send (Enter)")
                self.send_button.clicked.connect(self._submit_command)
                row.addWidget(self.send_button)
                return row

            def _log_area(self, QtWidgetsLocal):
                area = QtWidgetsLocal.QScrollArea()
                area.setWidgetResizable(True)
                area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.log_host = QtWidgetsLocal.QWidget()
                self.log_layout = QtWidgets.QVBoxLayout(self.log_host)
                self.log_layout.setContentsMargins(0, 0, 4, 0)
                self.log_layout.setSpacing(3)
                self.log_layout.addStretch(1)
                area.setWidget(self.log_host)
                area.setFrameShape(QtWidgetsLocal.QFrame.Shape.NoFrame)
                return area

            def _submit_command(self) -> None:
                text = self.command_edit.text().strip()
                if not text:
                    return
                self.command_edit.clear()
                if facade._question:
                    facade._fire("answer", text)
                else:
                    facade._fire("command", text)

        self.widget = _Panel()
        return self.widget

    # --- events from the app ---------------------------------------------
    def _fire(self, name: str, *args: Any) -> None:
        callback = {
            "command": self.on_command,
            "quick": self.on_quick,
            "listen": self.on_listen,
            "stop": self.on_stop,
            "answer": self.on_answer,
            "settings": self.on_settings,
            "home": self.on_hide,
            "confirm": self.on_confirm,
            "quit": self.on_quit,
        }.get(name)
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            logger.exception("panel callback %s failed", name)

    # --- live updates -----------------------------------------------------
    def apply_state(self, state: Dict[str, Any]) -> None:
        """Update the panel from a bridge status snapshot."""
        self._state.update(state)
        if self.widget is None:
            return

        connection = self._labels.get("connection")
        if connection is not None:
            ready = bool(state.get("model_ready"))
            connection.setText("Connected" if ready else "Offline — no key")
            connection.setStyleSheet(f"color: {PALETTE['connected'] if ready else PALETTE['offline']};")
        model = self._labels.get("model")
        if model is not None:
            model.setText(str(state.get("model") or "no model")[:34])

        watching = self._labels.get("watching")
        if watching is not None:
            what = str(state.get("watching_what") or "")
            watching.setText(f"Watching: {what}" if state.get("watching") else "Not watching the screen")

        header = self._labels.get("header_state")
        if header is not None:
            if state.get("busy"):
                header.setText(str(state.get("task") or "working…")[:44])
            elif state.get("agent_state"):
                header.setText(str(state["agent_state"]))
            elif state.get("watching"):
                header.setText("watching")

        dot = getattr(self.widget, "status_dot", None)
        if dot is not None:
            accent = state_color(str(state.get("agent_state") or ("idle" if not state.get("busy") else "thinking")))
            dot.setStyleSheet(f"color: {accent}; font-size: 12px;")

        activity = self._labels.get("activity")
        if activity is not None:
            pieces = []
            if state.get("actions"):
                pieces.append(str(state["actions"])[:60])
            if state.get("input_backend") and state.get("input_backend") != "none":
                pieces.append(f"input: {state['input_backend']}")
            activity.setText(" · ".join(pieces))

        busy = bool(state.get("busy"))
        if "listen" in self._buttons:
            self._buttons["listen"].setEnabled(not busy)
        if "stop" in self._buttons:
            self._buttons["stop"].setEnabled(busy)

        if state.get("question"):
            self.set_question(str(state["question"]))
        confirm = state.get("confirm")
        if isinstance(confirm, dict):
            self.set_confirmation(str(confirm.get("token", "")), str(confirm.get("prompt", "")))
        elif confirm is None and self._confirm_token:
            self.set_confirmation("", "")

    def set_state_expression(self, state: str) -> None:
        """Mirror the mascot's expression in the mini mascot and status dot."""
        widget = self.widget
        if widget is None:
            return
        mini = getattr(widget, "mini", None)
        if mini is not None:
            mini.state = state
            mini.update()
        self.apply_state({"agent_state": state})

    def log_action(self, result: Any) -> None:
        """Append one action to the visible log."""
        if self.widget is None:
            return
        QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")
        ok = bool(getattr(result, "ok", True))
        blocked = bool(getattr(result, "blocked", False))
        message = getattr(result, "message", "") or getattr(result, "describe", lambda: "")()
        duration = getattr(result, "duration", 0.0)
        accent = PALETTE["success"] if ok else (PALETTE["offline"] if blocked else PALETTE["error"])
        marker = "✔" if ok else ("⚠" if blocked else "✕")
        row = QtWidgets.QLabel(
            f"<span style='color:{accent}'>{marker}</span> {str(message)[:78]}"
            f"<span style='color:{PALETTE['panel_faint']}'> · {duration:.1f}s</span>"
        )
        row.setTextFormat(lazy.load("PySide6.QtCore", extra="ui").Qt.TextFormat.RichText)
        row.setWordWrap(True)
        layout = getattr(self.widget, "log_layout", None)
        if layout is None:
            return
        layout.insertWidget(max(0, layout.count() - 1), row)
        self._log_rows.append(row)
        while len(self._log_rows) > 60:
            old = self._log_rows.pop(0)
            try:
                old.setParent(None)
                old.deleteLater()
            except Exception:
                pass

    def focus_input(self) -> None:
        """Put the caret in the task box — what a click on the mascot should do.

        Qt refuses focus to a window it has not activated, so the panel is raised
        and activated first; otherwise the click appears to do nothing, which is
        precisely the complaint this avoids.
        """
        if self.widget is None:
            return
        try:
            self.widget.raise_()
            self.widget.activateWindow()
        except Exception as error:  # pragma: no cover - platform dependent
            logger.debug("could not activate the panel: %s", error)
        edit = getattr(self.widget, "command_edit", None)
        if edit is not None:
            edit.setFocus()

    def set_question(self, question: str) -> None:
        """Show (or clear) the agent's question above the input box."""
        self._question = question or ""
        if self.widget is None:
            return
        edit = getattr(self.widget, "command_edit", None)
        if edit is None:
            return
        if question:
            edit.setPlaceholderText(f"Naveed asks: {question[:70]}")
            edit.setStyleSheet(f"border: 1px solid {PALETTE['speaking']};")
            edit.setFocus()
        else:
            edit.setPlaceholderText("Tell Naveed what to do on this screen…")
            edit.setStyleSheet("")

    def set_confirmation(self, token: str, prompt: str) -> None:
        """Show the Allow / Deny strip for a destructive action."""
        self._confirm_token = token
        if self.widget is None:
            return
        QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")
        layout = getattr(self.widget, "log_layout", None)
        if layout is None:
            return
        if not token:
            existing = self.widget.__dict__.pop("confirm_row", None)
            if existing is not None:
                try:
                    existing.setParent(None)
                    existing.deleteLater()
                except Exception:
                    pass
            return
        if self.widget.__dict__.get("confirm_row") is not None:
            return
        row = QtWidgets.QFrame()
        row.setObjectName("Card")
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(9, 6, 9, 6)
        row_layout.setSpacing(6)
        label = QtWidgets.QLabel(prompt[:90])
        label.setWordWrap(True)
        label.setObjectName("Muted")
        row_layout.addWidget(label, 1)
        allow = QtWidgets.QPushButton("Allow")
        allow.setObjectName("Primary")
        allow.setFixedWidth(60)
        allow.clicked.connect(lambda: self._answer_confirmation(token, True))
        deny = QtWidgets.QPushButton("Deny")
        deny.setObjectName("Danger")
        deny.setFixedWidth(56)
        deny.clicked.connect(lambda: self._answer_confirmation(token, False))
        row_layout.addWidget(allow)
        row_layout.addWidget(deny)
        layout.insertWidget(max(0, layout.count() - 1), row)
        self.widget.confirm_row = row

    def _answer_confirmation(self, token: str, approved: bool) -> None:
        self.set_confirmation("", "")
        self._fire("confirm", token, approved)

    # --- settings sheet -----------------------------------------------------
    def toggle_settings(self) -> None:
        """Open or close the settings sheet."""
        self._settings_open = not self._settings_open
        if self.widget is None:
            return
        existing = self.widget.__dict__.pop("settings_sheet", None)
        if existing is not None:
            try:
                existing.setParent(None)
                existing.deleteLater()
            except Exception:
                pass
        if self._settings_open:
            self.widget.settings_sheet = self._build_settings()

    def _build_settings(self):
        """The settings sheet: model, key, provider, look and safety."""
        QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")
        panel = self.widget
        sheet = QtWidgets.QFrame(panel)
        sheet.setObjectName("Glass")
        layout = QtWidgets.QVBoxLayout(sheet)
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(7)

        title = QtWidgets.QLabel("Settings")
        title.setObjectName("Title")
        layout.addWidget(title)

        provider_row = QtWidgets.QHBoxLayout()
        provider_row.addWidget(QtWidgets.QLabel("Provider"))
        provider = QtWidgets.QComboBox()
        provider.addItems(["custom", *sorted(PROVIDER_PRESETS)])
        provider.setCurrentText(_provider_key(self.config.llm.base_url))
        provider_row.addWidget(provider, 1)
        layout.addLayout(provider_row)

        base_row = QtWidgets.QHBoxLayout()
        base_row.addWidget(QtWidgets.QLabel("Endpoint"))
        base_url = QtWidgets.QLineEdit(self.config.llm.base_url)
        base_row.addWidget(base_url, 1)
        layout.addLayout(base_row)

        model_row = QtWidgets.QHBoxLayout()
        model_row.addWidget(QtWidgets.QLabel("Model"))
        model = QtWidgets.QLineEdit(self.config.llm.model)
        model_row.addWidget(model, 1)
        layout.addLayout(model_row)

        key_row = QtWidgets.QHBoxLayout()
        key_row.addWidget(QtWidgets.QLabel("API key"))
        api_key = QtWidgets.QLineEdit(self.config.llm.api_key)
        api_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        api_key.setPlaceholderText("leave empty for a local model")
        key_row.addWidget(api_key, 1)
        layout.addLayout(key_row)

        size_row = QtWidgets.QHBoxLayout()
        size_row.addWidget(QtWidgets.QLabel("Mascot size"))
        size = QtWidgets.QSlider(lazy.load("PySide6.QtCore", extra="ui").Qt.Orientation.Horizontal)
        size.setRange(96, 320)
        size.setValue(int(self.config.overlay.size))
        size_row.addWidget(size, 1)
        layout.addLayout(size_row)

        on_top = QtWidgets.QCheckBox("Always on top")
        on_top.setChecked(bool(self.config.overlay.always_on_top))
        layout.addWidget(on_top)
        watch = QtWidgets.QCheckBox("Watch my screen in the background")
        watch.setChecked(self.config.capture.interval > 0)
        layout.addWidget(watch)
        confirm = QtWidgets.QCheckBox("Ask before destructive actions")
        confirm.setChecked(bool(self.config.safety.confirm_destructive))
        layout.addWidget(confirm)
        dry = QtWidgets.QCheckBox("Dry run (show what it would do, do nothing)")
        dry.setChecked(bool(self.config.safety.dry_run))
        layout.addWidget(dry)
        voice = QtWidgets.QCheckBox("Speak replies out loud")
        voice.setChecked(self.config.voice.tts != "none")
        layout.addWidget(voice)

        save_row = QtWidgets.QHBoxLayout()
        save_row.addStretch(1)
        save = QtWidgets.QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(
            lambda: self._save_settings(
                {
                    "llm.base_url": base_url.text().strip(),
                    "llm.model": model.text().strip(),
                    "llm.api_key": api_key.text().strip(),
                    "overlay.size": int(size.value()),
                    "overlay.always_on_top": bool(on_top.isChecked()),
                    "capture.interval": 2.0 if watch.isChecked() else 0.0,
                    "safety.confirm_destructive": bool(confirm.isChecked()),
                    "safety.dry_run": bool(dry.isChecked()),
                    "voice.tts": "auto" if voice.isChecked() else "none",
                }
            )
        )
        save_row.addWidget(save)
        layout.addLayout(save_row)

        hint = QtWidgets.QLabel("A plain-text copy lives in ~/.naveed/config.env")
        hint.setObjectName("Faint")
        layout.addWidget(hint)

        layout_rect = panel.rect()
        sheet.setGeometry(10, 10, layout_rect.width() - 20, min(layout_rect.height() - 20, 380))
        sheet.raise_()
        sheet.show()
        return sheet

    def _save_settings(self, values: Dict[str, Any]) -> None:
        if self.on_settings is not None:
            try:
                self.on_settings(values)
            except Exception:
                logger.exception("saving settings failed")
        self.toggle_settings()

    # --- window operations ---------------------------------------------
    def show(self, *, position: Optional[Tuple[int, int]] = None, near: Optional[Tuple[int, int, int]] = None) -> None:
        """Show the panel, optionally anchored above the mascot."""
        widget = self.build()
        x, y = position or self.anchor_position(near)
        widget.move(int(x), int(y))
        widget.show()
        widget.raise_()
        self.apply_state(self._state)

    def anchor_position(self, near: Optional[Tuple[int, int, int]] = None) -> Tuple[int, int]:
        """Placement above (or beside) the mascot, kept inside the screen."""
        from .window import _primary_screen_size

        screen_w, screen_h = _primary_screen_size()
        if near is None:
            x = int(screen_w / 2 - PANEL.width / 2)
            y = int(screen_h * 0.18)
            return x, y
        mascot_x, mascot_y, mascot_size = near
        anchor = self.config.overlay.panel_anchor
        gap = 12

        def above() -> Tuple[int, int]:
            return mascot_x + mascot_size - PANEL.width, mascot_y - PANEL.height - gap

        def below() -> Tuple[int, int]:
            return mascot_x + mascot_size - PANEL.width, mascot_y + mascot_size + gap

        if anchor == "below":
            x, y = below()
        elif anchor == "left":
            x, y = mascot_x - PANEL.width - gap, mascot_y
        elif anchor == "right":
            x, y = mascot_x + mascot_size + gap, mascot_y
        else:  # above (default)
            x, y = above()

        # Flip to the other side when the preferred one does not fit. The mascot
        # now starts *below the camera* at the top of the screen, where "above"
        # has no room — clamping there would stack the panel on top of the
        # character, which looks broken and hides the thing the user clicked.
        margin = 8
        if anchor in ("above", "below") and (y < margin or y + PANEL.height > screen_h - margin):
            other = below() if (anchor == "above" or y < margin) else above()
            if margin <= other[1] and other[1] + PANEL.height <= screen_h - margin:
                x, y = other
        elif anchor in ("left", "right") and (x < margin or x + PANEL.width > screen_w - margin):
            other = (mascot_x - PANEL.width - gap, mascot_y) if anchor == "right" else (mascot_x + mascot_size + gap, mascot_y)
            if margin <= other[0] and other[0] + PANEL.width <= screen_w - margin:
                x, y = other

        x = max(margin, min(x, screen_w - PANEL.width - margin))
        y = max(margin, min(y, screen_h - PANEL.height - margin))
        return int(x), int(y)

    def hide(self) -> None:
        if self.widget is not None:
            self.widget.hide()

    def toggle(self, *, near: Optional[Tuple[int, int, int]] = None) -> bool:
        """Show/hide the panel. Returns True when it is now visible."""
        widget = self.build()
        if widget.isVisible():
            widget.hide()
            return False
        self.show(near=near)
        return True

    @property
    def visible(self) -> bool:
        return bool(self.widget is not None and self.widget.isVisible())

    def set_mute(self, muted: bool) -> None:
        self.muted = muted
        button = getattr(self.widget, "mute_button", None) if self.widget else None
        if button is not None:
            button.update()

    def toggle_mute(self) -> bool:
        self.set_mute(not self.muted)
        if self.on_toggle_mute is not None:
            self.on_toggle_mute(self.muted)
        return self.muted

    def close(self) -> None:
        widget = self.widget
        self.widget = None
        if widget is not None:
            try:
                widget.close()
                widget.deleteLater()
            except Exception:
                pass


def build_mini_mascot(parent):
    """Create the 38px mascot portrait shown inside the status card.

    A function rather than a class, because Qt widgets must be constructed after
    their module has imported Qt, and a class factory would fight Python's own
    ``__init__`` rules.  The result is a normal ``QWidget`` that paints the
    mascot at a fraction of its usual size.
    """
    QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")

    class _Mini(QtWidgets.QWidget):
        def __init__(self, parent_widget) -> None:
            super().__init__(parent_widget)
            self.state = "idle"

        def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
            QtGuiLocal = lazy.load("PySide6.QtGui", extra="ui")
            from ..render.qt_canvas import QtCanvas

            painter = QtGuiLocal.QPainter(self)
            try:
                canvas = QtCanvas(painter, self.width(), self.height())
                side = min(self.width(), self.height()) - 2
                paint_mascot(
                    canvas,
                    1,
                    1,
                    side,
                    state=self.state,
                    blink=1.0,
                    mouth=0.3 if self.state in ("speaking", "listening", "success") else 0.0,
                    phase=time.time(),
                    shadow=False,
                    glow=False,
                )
            finally:
                painter.end()

    return _Mini(parent)


def draw_icon_pixmap(QtGui, name: str, size: int = 18, color: str = "#C7CEDD") -> Any:
    """Render one vector icon into a ``QPixmap`` (transparent background)."""
    from ..render.qt_canvas import QtCanvas

    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtGui.QColor(0, 0, 0, 0))
    painter = QtGui.QPainter(pixmap)
    try:
        canvas = QtCanvas(painter, size, size)
        draw_icon(canvas, name, 0, 0, size, color)
    finally:
        painter.end()
    return pixmap


def build_icon_button(QtWidgets) -> Any:
    """A small square button that paints a vector icon by name.

    Subclassing ``QPushButton`` and overriding ``paintEvent`` (instead of setting
    a QIcon) keeps the hover background from the stylesheet while the icon itself
    stays a vector path, so it is crisp on every DPI.
    """
    from .. import lazy as _lazy

    class _IconButton(QtWidgets.QPushButton):
        def __init__(self, icon_name: str) -> None:
            super().__init__("")
            self.icon_name = icon_name
            self.setObjectName("Icon")
            self.setFixedSize(26, 24)
            self.setCursor(_lazy.load("PySide6.QtCore", extra="ui").Qt.CursorShape.PointingHandCursor)

        def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
            super().paintEvent(event)
            QtGuiLocal = _lazy.load("PySide6.QtGui", extra="ui")
            from ..render.qt_canvas import QtCanvas

            painter = QtGuiLocal.QPainter(self)
            try:
                canvas = QtCanvas(painter, self.width(), self.height())
                side = min(self.width(), self.height()) - 8
                draw_icon(canvas, self.icon_name, (self.width() - side) / 2.0, (self.height() - side) / 2.0, side, PALETTE["panel_muted"])
            finally:
                painter.end()

    return _IconButton


def _MuteButton(QtWidgets, facade):
    """The speaker icon, which swaps to the muted variant when voice is off."""
    button_class = build_icon_button(QtWidgets)

    class _Mute(button_class):
        def __init__(self) -> None:
            super().__init__("speaker")
            self.setToolTip("Mute or unmute Naveed's voice")

        def paintEvent(self, event) -> None:  # noqa: N802
            self.icon_name = "speaker_muted" if facade.muted else "speaker"
            super().paintEvent(event)

    button = _Mute()
    button.clicked.connect(lambda: facade.toggle_mute())
    return button


def _provider_key(base_url: str) -> str:
    """Match a base URL back to one of the known provider presets."""
    for name, preset in PROVIDER_PRESETS.items():
        if preset["base_url"].rstrip("/") == (base_url or "").rstrip("/"):
            return name
    return "custom"
