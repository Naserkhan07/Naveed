"""Qt glue: turns :class:`~naveed.agent.bridge.AgentBridge` callbacks into UI.

The agent does its work on worker threads and knows nothing about Qt.  This file
owns the one place where that boundary is crossed, using a ``QObject`` with Qt
signals, because a signal emitted from a worker thread is delivered on the GUI
thread by Qt's own event loop — the correct, race-free way to touch widgets.

It also builds and wires the three surfaces the user interacts with:

* the **mascot** (:mod:`naveed.overlay.window`) — always on top, click to talk;
* the **panel** (:mod:`naveed.overlay.panel`) — status, shortcuts, chat;
* the **tray** (:mod:`naveed.overlay.tray`) — when you want the mascot gone but
  Naveed still alive.

and the optional global hotkey (:mod:`naveed.overlay.hotkeys`).
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List, Optional

from .. import lazy
from ..agent.bridge import AgentBridge, BridgeEvents
from ..config import Config
from .panel import ControlPanel
from .window import MascotWindow

logger = logging.getLogger("naveed.overlay")


def _open_in_browser(url: str) -> None:
    """Hand the URL to the desktop's browser, quietly if there is not one."""
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        logger.debug("could not open a browser for %s", url)

__all__ = ["OverlayApp"]


class OverlayApp:
    """Owns the QApplication and every visible surface."""

    def __init__(self, config: Config, *, serve: bool = False, open_browser: bool = False) -> None:
        self.config = config
        #: run the browser front end alongside the mascot (same bridge, one bot)
        self.serve = bool(serve)
        self.open_browser = bool(open_browser)
        #: the HTTP server, when it is running in this process
        self.server: Optional[Any] = None
        self.mascot = MascotWindow(
            config,
            on_click=self._on_mascot_click,
            on_toggle_panel=self._on_toggle_panel,
            on_drag=self._on_mascot_drag,
            on_command=self._on_slash_command,
            on_settings=self._on_settings,
            on_quit=self.quit,
        )
        self.panel = ControlPanel(
            config,
            on_command=self._on_command,
            on_quick=self._on_quick,
            on_listen=self._on_listen,
            on_stop=self._on_stop,
            on_answer=self._on_answer,
            on_confirm=self._on_confirm,
            on_settings=self._on_settings_saved,
            on_hide=self._on_hide,
            on_quit=self.quit,
            on_toggle_mute=self._on_toggle_mute,
        )
        self.bridge = AgentBridge(
            config,
            events=BridgeEvents(
                on_status=self._on_agent_status,
                on_say=self._on_agent_say,
                on_action=self._on_agent_action,
                on_question=self._on_agent_question,
                on_task=self._on_agent_task,
                on_state=self._on_agent_state,
                on_error=self._on_agent_error,
            ),
            hide_overlay=self._hide_for_capture,
            show_overlay=self._show_after_capture,
            click_through=self._set_click_through,
        )
        self.voice: Optional[Any] = None
        self.tray: Optional[Any] = None
        self.hotkeys: Optional[Any] = None
        self._qt: Dict[str, Any] = {}
        #: the one QApplication, created in build() before any widget
        self.application: Optional[Any] = None
        self._questions: List[str] = []
        self._last_spoken = ""

    # --- construction -----------------------------------------------------
    def build(self) -> None:
        """Create the Qt application, widget tree and long-lived helpers.

        The ``QApplication`` is made **first**, before a single QWidget exists.
        Qt is explicit that a widget may only be constructed once an application
        object is present — without this, Windows printed
        ``QWidget: Must construct a QApplication before a QWidget`` and the
        mascot silently failed to appear (the widgets existed but Qt would not
        manage them).
        """
        QtCore = lazy.load("PySide6.QtCore", extra="ui")
        QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")
        self._qt = {"QtCore": QtCore, "QtWidgets": QtWidgets}

        # Reuse the running application if there is one (the tray, or a second
        # `build()`), otherwise create it — and never construct a widget first.
        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([sys.argv[0] if sys.argv else "naveed"])
            app.setApplicationName("Naveed")
            app.setApplicationDisplayName("Naveed")
            app.setQuitOnLastWindowClosed(False)
        self.application = app

        self.mascot.build()
        self.panel.build()
        self._wire_signals()

        # The browser front end, when it was asked for: same bridge, so a task
        # typed in the browser moves the mascot on screen and vice versa. Read
        # defensively — build() is also called by tests with a stripped config.
        web = getattr(self.config, "web", None)
        if getattr(self, "serve", False) and getattr(web, "enabled", True):
            self.start_browser()


        # Voice (optional, offline): the mascot's mouth follows the speaker.
        try:
            from ..speech import VoiceCallbacks, VoiceLoop

            self.voice = VoiceLoop(
                self.config,
                VoiceCallbacks(
                    on_state=self._on_voice_state,
                    on_level=self._on_voice_level,
                    on_text=self._on_voice_text,
                    on_error=self._on_agent_say,
                    on_speech=self._on_speech_event,
                ),
            )
        except Exception as error:  # speech is optional by design
            logger.info("voice stack unavailable: %s", error)
            self.voice = None

        # Tray icon, when the platform has one.
        if self.config.overlay.tray:
            try:
                from .tray import TrayIcon

                self.tray = TrayIcon(
                    self.config,
                    on_open_page=self._open_page if self.server else None,
                    on_toggle_panel=lambda: self._on_toggle_panel(),
                    on_listen=self._on_listen,
                    on_look=lambda: self._on_quick("look"),
                    on_screenshot=lambda: self._on_quick("screenshot"),
                    on_settings=lambda: self.panel.toggle_settings(),
                    on_quit=self.quit,
                ).build()
                self.tray.show()
            except Exception as error:
                logger.info("tray unavailable: %s", error)
                self.tray = None

        # Global hotkey, when one is configured and a hook library exists.
        if self.config.overlay.hotkey:
            try:
                from .hotkeys import HotkeyManager

                self.hotkeys = HotkeyManager(self.config.overlay.hotkey, self._on_hotkey)
                self.hotkeys.start()
            except Exception as error:
                logger.info("global hotkey unavailable: %s", error)
                self.hotkeys = None

    def _wire_signals(self) -> None:
        """Route worker-thread callbacks through Qt signals (thread-safe)."""
        QtCore = self._qt["QtCore"]
        facade = self

        class _Relay(QtCore.QObject):
            """Receives agent events on any thread and re-emits on the GUI thread."""

            status = QtCore.Signal(str, str)
            say = QtCore.Signal(str)
            action = QtCore.Signal(object)
            question = QtCore.Signal(str)
            task = QtCore.Signal(object)
            state = QtCore.Signal(object)
            error = QtCore.Signal(str)
            speech = QtCore.Signal(object)
            level = QtCore.Signal(float)
            #: the global hotkey fires on pynput's listener thread; touching
            #: widgets from there is undefined behaviour, so it comes through a
            #: signal like every other cross-thread call.
            wake = QtCore.Signal()
            #: microphone / speech state arrives from the speech threads
            voice_state = QtCore.Signal(str)

            def __init__(self) -> None:
                super().__init__()
                self.status.connect(facade._apply_agent_status)
                self.say.connect(facade._apply_agent_say)
                self.action.connect(facade._apply_agent_action)
                self.question.connect(facade._apply_agent_question)
                self.task.connect(facade._apply_agent_task)
                self.state.connect(facade._apply_agent_state)
                self.error.connect(facade._apply_agent_error)
                self.speech.connect(facade._apply_speech_event)
                self.level.connect(facade._apply_level)
                self.wake.connect(facade._on_mascot_click)
                self.voice_state.connect(facade._apply_voice_state)

        self._relay = _Relay()

    # --- running ------------------------------------------------------------
    def run(self) -> int:
        """Show everything and enter the Qt event loop.

        ``build()`` comes first because it is what loads Qt and fills ``_qt``:
        reading the module dictionary before it is populated crashed the *main*
        entry point with ``KeyError: 'QtWidgets'`` on every platform, before the
        mascot could ever appear.
        """
        self.build()
        QtWidgets = self._qt["QtWidgets"]

        if not self.config.overlay.start_hidden:
            self.mascot.show()
        if self.config.overlay.show_panel_on_start:
            self.panel.show(near=(*self.mascot.position(), self.config.overlay.size))
        # Mute the panel's speaker button when there is no speech engine at all.
        self.panel.set_mute(self.bridge.config.voice.tts == "none")

        self.bridge.start()
        if self.bridge.model_ready:
            # "Configured" is not the same as "answering" — say which one it is,
            # because a silent mascot in front of a dead endpoint looks broken.
            reachable, reason = self._probe_model()
            if reachable:
                self.bridge.say("I am here. Click me and tell me what to do.")
            else:
                logger.info("model endpoint is not answering: %s", reason)
                self.bridge.say(f"I am on screen, but my model is not answering — {reason} Open settings to fix it.")
        else:
            self.bridge.say(
                "I am watching your screen, but I have no LLM API yet — open settings and point me at one."
            )
        self.panel.apply_state(self.bridge.status())

        app = self.application or QtWidgets.QApplication.instance()
        if app is None:  # pragma: no cover - build() always creates one
            raise RuntimeError("no QApplication: call build() before run()")
        # Keep running when the last window is hidden (the tray owns the app).
        app.setQuitOnLastWindowClosed(False)
        return int(app.exec())

    def _open_page(self) -> None:
        """Tray/toolbar action: open the browser front end, if it is running."""
        if self.server is not None:
            _open_in_browser(self.server.url)

    def start_browser(self, *, port: Optional[int] = None) -> Optional[str]:
        """Serve the browser front end on this process's bot; return its URL.

        Failure is not fatal: the mascot is the main way to use Naveed, so a port
        clash or a sandbox that forbids listening must not stop it appearing.
        """
        if self.server is not None:
            return self.server.url
        try:
            from ..server import BotServer

            self.server = BotServer(
                self.config,
                bridge=self.bridge,
                port=port if port is not None else self.config.web.port,
            ).start()
        except Exception as error:
            logger.warning("browser front end could not start: %s", error)
            self.server = None
            return None
        url = self.server.url
        logger.info("browser front end: %s", url)
        try:
            print(f"Naveed is also in your browser: {url}")
        except Exception:  # pragma: no cover - a closed stdout must not matter
            pass
        if self.open_browser or self.config.web.open_browser:
            _open_in_browser(url)
        return url

    def quit(self) -> None:
        """Shut everything down cleanly."""
        try:
            if self.server is not None:
                self.server.stop()
                self.server = None
            if self.hotkeys is not None:
                self.hotkeys.stop()
            if self.voice is not None:
                self.voice.close()
            if self.tray is not None:
                self.tray.hide()
            self.bridge.stop()
            self.panel.close()
            self.mascot.close()
        finally:
            app = self._qt.get("QtWidgets")
            if app is not None:
                instance = app.QApplication.instance()
                if instance is not None:
                    instance.quit()

    # --- mascot / panel interactions -----------------------------------------
    def _probe_model(self) -> tuple:
        """Ask the endpoint whether it answers. Never blocks the UI for long."""
        try:
            from ..agent.llm import LLMClient

            return LLMClient(self.config.llm).probe(timeout=1.5)
        except Exception as error:  # pragma: no cover - defensive
            logger.debug("model probe failed: %s", error)
            return True, ""

    def _on_mascot_click(self) -> None:
        """Single click on the mascot = talk (the user's chosen wake action).

        The panel comes up either way: clicking the character is how the user asks
        for its attention, and a click that changes nothing on screen reads as a
        broken app.
        """
        self.panel.show(near=(*self.mascot.position(), self.config.overlay.size))
        if self.voice is not None and self.voice.can_listen:
            started = self.voice.begin()
            if started:
                self.mascot.set_state("listening")
                self.panel.apply_state({"agent_state": "listening"})
                return
        # No microphone, or it refused to start: type instead of talking.
        self.panel.focus_input()
        self.bridge.say("I cannot hear you — no microphone is available. Type the task in the panel instead.")

    def _on_toggle_panel(self) -> None:
        self.panel.toggle(near=(*self.mascot.position(), self.config.overlay.size))

    def _on_mascot_drag(self, x: int, y: int) -> None:
        """Keep the panel glued to the mascot while it is dragged."""
        if self.config.overlay.panel_pinned and self.panel.visible:
            self.panel.show(near=(x, y, self.config.overlay.size))

    def _on_slash_command(self, command: str) -> None:
        if command == "__screenshot__":
            self.bridge.quick_screenshot()
            return
        self._on_command(command)

    def _on_command(self, text: str) -> None:
        """A typed task from the panel."""
        self.mascot.set_state("thinking")
        if not self.bridge.submit(text):
            return
        self.panel.apply_state({"mascot_state": "thinking"})

    def _on_quick(self, key: str) -> None:
        """A colourful shortcut button."""
        if key == "screenshot":
            self.bridge.quick_screenshot()
            return
        self.mascot.set_state("thinking")
        self.bridge.run_quick(key)

    def _on_listen(self) -> None:
        self._on_mascot_click()

    def _on_stop(self) -> None:
        if self.voice is not None:
            self.voice.cancel()
        self.bridge.cancel()
        self.mascot.set_state("idle")

    def _on_answer(self, text: str) -> None:
        self.bridge.answer(text)
        self.panel.set_question("")

    def _on_confirm(self, token: str, approved: bool) -> None:
        self.bridge.resolve_confirmation(token, approved)

    def _on_hotkey(self) -> None:
        """Global hotkey pressed: behave exactly like clicking the mascot.

        Called from pynput's thread, so it must not touch a widget directly —
        the relay re-emits on the GUI thread.
        """
        relay = getattr(self, "_relay", None)
        if relay is not None:
            relay.wake.emit()
            return
        self._on_mascot_click()

    def _on_hide(self) -> None:
        self.panel.hide()
        self.mascot.show()

    def _on_settings(self) -> None:
        self.panel.show(near=(*self.mascot.position(), self.config.overlay.size))
        self.panel.toggle_settings()

    def _on_settings_saved(self, values: Dict[str, Any]) -> None:
        try:
            path = self.bridge.update_settings(**values)
        except Exception as error:
            self.bridge.say(f"I could not save those settings: {error}")
            return
        self.config = self.bridge.config
        self.mascot.config = self.config
        self.panel.config = self.config
        self.mascot.set_state("success")
        self.bridge.say(f"Saved to {path}.")
        self.panel.apply_state(self.bridge.status())

    def _on_toggle_mute(self, muted: bool) -> None:
        if self.voice is not None:
            self.voice.speaker.enabled = not muted
            if muted:
                self.voice.stop_speaking()

    # --- voice events ---------------------------------------------------------
    def _on_voice_state(self, state: str) -> None:
        """Listening/speaking state, reported by the speech threads.

        Qt widgets belong to the GUI thread; the recorder and the speaker each run
        on their own, so these hop across on a signal rather than being poked
        directly from another thread (which works until it does not, and then
        crashes the whole app on Windows).
        """
        relay = getattr(self, "_relay", None)
        if relay is not None:
            relay.voice_state.emit(str(state))
            return
        self._apply_voice_state(str(state))

    def _apply_voice_state(self, state: str) -> None:
        self.mascot.set_state(state)
        self.panel.set_state_expression(state)

    def _on_voice_level(self, level: float) -> None:
        relay = getattr(self, "_relay", None)
        if relay is not None:
            relay.level.emit(float(level))
            return
        self._apply_level(float(level))

    def _on_voice_text(self, text: str) -> None:
        self.bridge.submit(text)

    def _on_speech_event(self, event: Any) -> None:
        try:
            self._relay.speech.emit(event)
        except Exception:
            pass

    def _apply_speech_event(self, event: Any) -> None:
        if getattr(event, "kind", "") == "level":
            self.mascot.set_speech_level(getattr(event, "level", 0.0))
        elif getattr(event, "kind", "") == "start":
            self.mascot.set_state("speaking")
            self.panel.set_state_expression("speaking")
        else:
            self.mascot.set_state("idle")
            self.panel.set_state_expression("idle")

    def _apply_level(self, level: float) -> None:
        self.mascot.set_microphone_level(level)

    # --- agent events (already on the GUI thread via signals) -----------------
    def _on_agent_status(self, state: str, detail: str = "") -> None:
        self._relay.status.emit(state, detail)

    def _on_agent_say(self, text: str) -> None:
        self._relay.say.emit(text)

    def _on_agent_action(self, result: Any) -> None:
        self._relay.action.emit(result)

    def _on_agent_question(self, question: str) -> None:
        self._relay.question.emit(question)

    def _on_agent_task(self, task: Any) -> None:
        self._relay.task.emit(task)

    def _on_agent_state(self, state: Dict[str, Any]) -> None:
        self._relay.state.emit(state)

    def _on_agent_error(self, message: str) -> None:
        self._relay.error.emit(message)

    # --- GUI-thread application ------------------------------------------------
    def _apply_agent_status(self, state: str, detail: str = "") -> None:
        if state in ("thinking", "acting", "listening", "speaking", "waiting"):
            self.mascot.set_state("thinking" if state == "thinking" else state)
        elif state in ("done", "success"):
            self.mascot.set_state("success")
            self._reset_soon()
        elif state in ("failed", "error"):
            self.mascot.set_state("error")
            self._reset_soon()
        elif state in ("cancelled", "idle"):
            self.mascot.set_state("idle")
        self.panel.set_state_expression(self.mascot.state)
        self.panel.apply_state(self.bridge.status())
        if detail:
            self.mascot.toast(_short(detail), seconds=5.0)

    def _apply_agent_say(self, text: str) -> None:
        if not text:
            return
        self._last_spoken = text
        self.mascot.toast(_short(text), seconds=6.0)
        self.panel.log_action(_SimpleResult(True, text, 0.0))
        if self.voice is not None and self.config.voice.tts != "none":
            self.voice.say(text)

    def _apply_agent_action(self, result: Any) -> None:
        self.panel.log_action(result)

    def _apply_agent_question(self, question: str) -> None:
        self.panel.set_question(question)
        self.panel.show(near=(*self.mascot.position(), self.config.overlay.size))
        self.mascot.set_state("listening")
        if self.voice is not None and self.config.voice.tts != "none":
            self.voice.say(question)

    def _apply_agent_task(self, task: Any) -> None:
        status = getattr(task, "status", None)
        value = getattr(status, "value", "done")
        if value == "done":
            self.mascot.set_state("success")
        elif value == "failed":
            self.mascot.set_state("error")
        self._reset_soon()

    def _apply_agent_state(self, payload: Dict[str, Any]) -> None:
        self.panel.apply_state(payload)
        if payload.get("mascot_state"):
            self.mascot.set_state(str(payload["mascot_state"]))
        if "confirm" in payload:
            confirm = payload.get("confirm")
            if isinstance(confirm, dict):
                self.panel.set_confirmation(str(confirm.get("token", "")), str(confirm.get("prompt", "")))
            else:
                self.panel.set_confirmation("", "")

    def _apply_agent_error(self, message: str) -> None:
        self.mascot.set_state("error")
        self.mascot.toast(_short(message), seconds=7.0)
        self.panel.log_action(_SimpleResult(False, message, 0.0))
        self._reset_soon()

    def _reset_soon(self, seconds: float = 3.0) -> None:
        """Return the mascot to idle a moment after a terminal state."""
        QtCore = self._qt.get("QtCore")
        if QtCore is None:
            return
        QtCore.QTimer.singleShot(int(seconds * 1000), self._become_idle)

    def _become_idle(self) -> None:
        if not self.bridge.busy and self.mascot.state in ("success", "error"):
            self.mascot.set_state("idle")

    # --- capture cooperation ----------------------------------------------------
    def _hide_for_capture(self) -> None:
        """Hide the overlay so Naveed never photographs itself."""
        self.mascot.hide_for_capture()
        if self.panel.visible:
            self.panel.hide()

    def _show_after_capture(self) -> None:
        self.mascot.show_after_capture()

    def _set_click_through(self, enabled: bool) -> None:
        """Let the agent's clicks through while it drives the mouse."""
        self.mascot.set_click_through(bool(enabled))


class _SimpleResult:
    """Minimal ActionResult-shaped object for text-only log lines."""

    def __init__(self, ok: bool, message: str, duration: float) -> None:
        self.ok = ok
        self.message = message
        self.duration = duration
        self.blocked = False


def _short(text: str, limit: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
