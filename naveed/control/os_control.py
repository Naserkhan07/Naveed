"""The agent's hands: turn one :class:`~naveed.control.actions.Action` into reality.

This is the layer where screenshots and input meet, and therefore where the
subtle bugs of desktop automation live.  It exists to solve four of them:

1. **Frame coordinates vs screen coordinates.**  The model is shown a bitmap and
   answers in bitmap pixels.  :meth:`OsController.global_point` converts through
   :meth:`naveed.screen.displays.Monitor.to_global`, so multi-monitor and HiDPI
   setups click the right pixel (the voiceuse repo's per-capture ``origin_x/origin_y``
   idea, kept and generalised).
2. **The companion getting in its own way.**  Naveed floats over the desktop, so
   every pointer action runs inside :meth:`_pointer_frame`, which asks the overlay
   to become click-through and the watcher to pause.  Without this the mascot
   would eat the click it was asked to make.
3. **Long operations on the UI thread.**  Actions block on purpose (they are real
   input events); the overlay calls this from a worker thread and receives results
   through signals.
4. **Platform-specific launching.**  ``open_app``/``open_url``/``focus_window``
   each have a real implementation per OS instead of "try xdg-open and hope".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import lazy
from ..config import Config
from ..screen.displays import Monitor, monitor_at_point, monitors_or_default, primary_monitor
from ..screen.focus import active_window
from .actions import Action, ActionError
from .input import InputController, InputError
from .keys import parse_hotkey
from .safety import RiskLevel, SafetyCheck, SafetyGuard

__all__ = ["ActionResult", "OsController"]


@dataclass
class ActionResult:
    """What happened when one action ran."""

    ok: bool
    action: Action
    message: str = ""
    risk: RiskLevel = RiskLevel.SAFE
    blocked: bool = False
    skipped: bool = False
    screen_changed: Optional[bool] = None
    duration: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.action.kind

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action.to_dict(),
            "description": self.action.describe(),
            "message": self.message,
            "risk": int(self.risk),
            "blocked": self.blocked,
            "skipped": self.skipped,
            "screen_changed": self.screen_changed,
            "duration": round(self.duration, 3),
        }


class OsController:
    """Executes actions on the real desktop."""

    def __init__(
        self,
        config: Config,
        *,
        watcher: Any = None,
        input_controller: Optional[InputController] = None,
        guard: Optional[SafetyGuard] = None,
        before_pointer: Optional[Callable[[], None]] = None,
        after_pointer: Optional[Callable[[], None]] = None,
        on_action: Optional[Callable[[ActionResult], None]] = None,
    ) -> None:
        self.config = config
        self.watcher = watcher
        self.safety = guard or SafetyGuard(config.safety)
        self.on_action = on_action
        self._before_pointer = before_pointer
        self._after_pointer = after_pointer
        self.input = input_controller or InputController(
            dry_run=config.safety.dry_run,
            before_pointer=self._pointer_hooks,
            after_pointer=self._release_pointer_hooks,
        )
        self.log: List[ActionResult] = []

    # --- hooks ---------------------------------------------------------
    def _pointer_hooks(self) -> None:
        """Make the overlay click-through and pause watching before input."""
        if self.watcher is not None:
            try:
                self.watcher.pause()
            except Exception:
                pass
        if self._before_pointer is not None:
            try:
                self._before_pointer()
            except Exception:
                pass

    def _release_pointer_hooks(self) -> None:
        if self.watcher is not None:
            try:
                self.watcher.resume()
            except Exception:
                pass
            try:
                self.watcher.capture.invalidate()
            except Exception:
                pass
        if self._after_pointer is not None:
            try:
                self._after_pointer()
            except Exception:
                pass

    # --- coordinates ---------------------------------------------------
    def global_point(self, action: Action, frame: Any = None, *, monitors: Optional[Sequence[Monitor]] = None) -> Optional[Tuple[int, int]]:
        """Convert an action's frame-local point into global screen coordinates.

        Falls back to treating the numbers as already-global when no frame is
        available, and clamps into the monitor so a model answering ``(9999, 9999)``
        hits the edge of the screen instead of a phantom coordinate.
        """
        if action.x is None or action.y is None:
            return None
        monitors = list(monitors or monitors_or_default())
        monitor: Optional[Monitor] = None
        frame_size: Optional[Tuple[int, int]] = None
        if frame is not None:
            monitor = getattr(frame, "monitor", None)
            size = getattr(frame, "size", None)
            if size:
                frame_size = (int(size[0]), int(size[1]))
        if monitor is None:
            # No frame: the point may still be global (e.g. straight from the panel).
            point = (int(round(action.x)), int(round(action.y)))
            monitor = monitor_at_point(point[0], point[1], monitors)
            return monitor.clamp_global(*point)
        return monitor.clamp_global(*monitor.to_global(action.x, action.y, frame_size=frame_size))

    # --- execution ------------------------------------------------------
    def perform(
        self,
        action: Action,
        *,
        frame: Any = None,
        context: str = "",
        raw_text: str = "",
        check: Optional[SafetyCheck] = None,
    ) -> ActionResult:
        """Run one action, safety-checked, with timings and a readable message."""
        started = time.time()
        decision = check or self.safety.review(action, context=context, raw_text=raw_text)
        if decision.blocked:
            result = ActionResult(
                ok=False,
                action=action,
                message=decision.denial_reason or "blocked for safety",
                risk=decision.risk,
                blocked=True,
            )
            return self._finish(result, started)

        if self.config.safety.dry_run:
            self.input.dry_run = True

        try:
            handler = getattr(self, f"_do_{action.kind}", None)
            if handler is None:
                raise ActionError(f"Naveed cannot perform '{action.kind}' yet.")
            message, payload = handler(action, frame)
            result = ActionResult(
                ok=True,
                action=action,
                message=message or action.describe(),
                risk=decision.risk,
                payload=payload or {},
            )
        except (ActionError, InputError) as error:
            result = ActionResult(ok=False, action=action, message=str(error), risk=decision.risk)
        except Exception as error:  # keep the loop alive, report honestly
            result = ActionResult(
                ok=False,
                action=action,
                message=f"{type(error).__name__}: {error}",
                risk=decision.risk,
            )
        return self._finish(result, started)

    def _finish(self, result: ActionResult, started: float) -> ActionResult:
        result.duration = time.time() - started
        self.log.append(result)
        if len(self.log) > 300:
            del self.log[:150]
        if self.on_action is not None:
            try:
                self.on_action(result)
            except Exception:
                pass
        return result

    # --- handlers: pointer ---------------------------------------------
    def _do_click(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        point = self.global_point(action, frame)
        if point is None:
            point = self._resolve_target_point(action, frame)
        if point is None:
            raise ActionError(f"could not work out where to click for {action.to_dict()!r}")
        self.input.click_at(point[0], point[1], count=1)
        return f"clicked at {point[0]},{point[1]}", {"point": point}

    def _do_double_click(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        point = self.global_point(action, frame) or self._resolve_target_point(action, frame)
        if point is None:
            raise ActionError("double click needs a location")
        self.input.click_at(point[0], point[1], count=2)
        return f"double-clicked at {point[0]},{point[1]}", {"point": point}

    def _do_right_click(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        point = self.global_point(action, frame) or self._resolve_target_point(action, frame)
        if point is None:
            raise ActionError("right click needs a location")
        self.input.click_at(point[0], point[1], button="right")
        return f"right-clicked at {point[0]},{point[1]}", {"point": point}

    def _do_middle_click(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        point = self.global_point(action, frame) or self._resolve_target_point(action, frame)
        if point is None:
            raise ActionError("middle click needs a location")
        self.input.click_at(point[0], point[1], button="middle")
        return f"middle-clicked at {point[0]},{point[1]}", {"point": point}

    def _do_move(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        point = self.global_point(action, frame)
        if point is None:
            raise ActionError("move needs coordinates")
        self.input.move_to(point[0], point[1])
        return f"moved to {point[0]},{point[1]}", {"point": point}

    def _do_drag(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        from .keys import normalize_drag_path

        raw_path = action.get("path")
        monitor = getattr(frame, "monitor", None)
        frame_size = tuple(getattr(frame, "size", ())) or None
        if raw_path:
            points = normalize_drag_path(raw_path)
            if monitor is not None and frame_size:
                points = [monitor.to_global(px, py, frame_size=frame_size) for px, py in points]
        else:
            start = self.global_point(action, frame)
            end_action = Action(kind="click", params={"x": action.get("to_x"), "y": action.get("to_y")})
            end = self.global_point(end_action, frame) if end_action.x is not None else None
            if start is None or end is None:
                raise ActionError("drag needs a start and an end point")
            points = [start, end]
        self.input.drag(points)
        return f"dragged {points[0]} -> {points[-1]}", {"path": points}

    def _do_scroll(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        amount = int(action.get("amount") or action.get("dy") or 400)
        point = self.global_point(action, frame)
        self.input.scroll(amount, dx=int(action.get("dx") or 0), x=point[0] if point else None, y=point[1] if point else None)
        return f"scrolled {amount}", {"amount": amount}

    # --- handlers: keyboard --------------------------------------------
    def _do_type(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        text = action.text
        limit = self.config.safety.typed_text_limit
        if len(text) > limit:
            text = text[:limit]
        self.input.type_text(text)
        return f"typed {len(text)} characters", {"characters": len(text)}

    def _do_key(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        self.input.press_key(action.key, action.keys)
        return f"pressed {action.key}", {}

    def _do_hotkey(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        chord = str(action.get("hotkey") or "")
        if not chord:
            parts = [*map(str, action.keys), action.key]
            chord = "+".join(part for part in parts if part)
        keys = parse_hotkey(chord)
        if not keys:
            raise ActionError(f"could not parse hotkey {chord!r}")
        if len(keys) == 1:
            self.input.press_key(keys[0])
        else:
            *modifiers, key = keys
            self.input.press_key(key, tuple(modifiers))
        return f"pressed {chord}", {"keys": keys}

    # --- handlers: navigation ------------------------------------------
    def _do_wait(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        seconds = float(action.get("seconds") or action.get("seconds_delay") or 1.0)
        seconds = min(max(seconds, 0.05), 30.0)
        time.sleep(seconds)
        return f"waited {seconds:g}s", {"seconds": seconds}

    def _do_screenshot(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        if self.watcher is None:
            raise ActionError("screen watching is not running")
        fresh = self.watcher.snapshot(fresh=True, save=True)
        path = fresh.saved_path or ""
        return (f"captured {fresh.width}x{fresh.height}", {"path": path, "width": fresh.width, "height": fresh.height})

    def _do_look(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        return self._do_screenshot(action, frame)

    def _do_open_url(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        url = str(action.get("url") or action.get("target") or "").strip()
        if not url:
            raise ActionError("open_url needs a url")
        if not url.startswith(("http://", "https://", "mailto:", "file://")):
            url = "https://" + url.lstrip("/")
        self.open_url(url)
        return f"opened {url}", {"url": url}

    def _do_open_app(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        app = str(action.get("app") or action.get("name") or action.get("target") or "").strip()
        if not app:
            raise ActionError("open_app needs an app name")
        ok, message = self.open_app(app)
        if not ok:
            raise ActionError(message)
        return message, {"app": app}

    def _do_open_file(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        path = str(action.get("path") or action.get("file") or action.get("target") or "").strip()
        if not path:
            raise ActionError("open_file needs a path")
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise ActionError(f"no such file or folder: {path}")
        self.open_path(path)
        return f"opened {path}", {"path": path}

    def _do_focus_window(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        title = str(action.get("title") or action.get("app") or action.get("target") or "").strip()
        if not title:
            raise ActionError("focus_window needs a window title or app name")
        ok, message = self.focus_window(title)
        if not ok:
            raise ActionError(message)
        return message, {"title": title}

    def _do_shell(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        command = str(action.get("command") or "").strip()
        if not command:
            raise ActionError("shell needs a command")
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=float(action.get("timeout") or 60),
        )
        output = (completed.stdout or completed.stderr or "").strip()
        return (f"ran: {command} (exit {completed.returncode})", {"stdout": completed.stdout, "stderr": completed.stderr, "exit": completed.returncode, "output": output[:2000]})

    # --- handlers: clipboard -------------------------------------------
    def _do_clipboard_get(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        text = self.clipboard_text()
        return f"clipboard: {text[:80]!r}", {"text": text}

    def _do_clipboard_set(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        text = action.text or str(action.get("clipboard") or "")
        self.set_clipboard_text(text)
        return f"copied {len(text)} characters", {"characters": len(text)}

    def _do_done(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        return str(action.get("summary") or "done"), {"terminal": True}

    def _do_ask(self, action: Action, frame: Any) -> Tuple[str, Dict[str, Any]]:
        return str(action.params.get("question") or ""), {"terminal": True, "question": action.params.get("question")}

    # --- target resolution ---------------------------------------------
    def _resolve_target_point(self, action: Action, frame: Any) -> Optional[Tuple[int, int]]:
        """Find a point for "click the Save button" when no coordinates were given.

        Strategy: ask OCR for the text (optional extra), take the centre of its
        box, and convert that through the frame's monitor.  With no OCR available
        the action fails *with an explanation* rather than clicking somewhere
        random — a small model guessing coordinates is worse than an honest error.
        """
        target = str(action.get("target") or action.get("element") or "").strip()
        if not target or frame is None:
            return None
        try:
            from .ocr import find_text

            matches = find_text(frame.image, target)
        except Exception:
            return None
        if not matches:
            return None
        best = matches[0]
        center_x = (best.left + best.right) / 2.0
        center_y = (best.top + best.bottom) / 2.0
        monitor = getattr(frame, "monitor", None)
        if monitor is None:
            return None
        return monitor.clamp_global(*monitor.to_global(center_x, center_y, frame_size=frame.size))

    # --- platform actions ------------------------------------------------
    def open_url(self, url: str) -> None:
        """Open a URL in the user's default browser."""
        if self.config.safety.dry_run:
            return
        if sys.platform.startswith("win"):
            os.startfile(url)  # type: ignore[attr-defined]
            return
        opener = "open" if sys.platform.startswith("darwin") else "xdg-open"
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_path(self, path: str) -> None:
        """Open a file or folder with the OS default handler."""
        if self.config.safety.dry_run:
            return
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
            return
        opener = "open" if sys.platform.startswith("darwin") else "xdg-open"
        subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_app(self, app: str) -> Tuple[bool, str]:
        """Launch an application by (fuzzy) name.

        Returns ``(ok, message)`` instead of raising so the planner can be told
        what failed and try an alternative (that is the whole point of a loop).
        """
        if self.config.safety.dry_run:
            return True, f"[dry run] would open {app}"
        platform = sys.platform
        try:
            if platform.startswith("win"):
                # `start` resolves App Paths (chrome, code, notepad, ...).
                subprocess.Popen(f'start "" "{app}"', shell=True)
                return True, f"opened {app}"
            if platform.startswith("darwin"):
                result = subprocess.run(["open", "-a", app], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return True, f"opened {app}"
                result = subprocess.run(["open", "-a", app + ".app"], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return True, f"opened {app}"
                return False, f"macOS could not find an app called {app!r}: {result.stderr.strip()}"

            candidates = [app, app.lower(), app.replace(" ", "-").lower()]
            for candidate in candidates:
                binary = shutil.which(candidate)
                if binary:
                    subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    return True, f"opened {app}"
            if shutil.which("gtk-launch"):
                for candidate in (app, app.title()):
                    result = subprocess.run(["gtk-launch", candidate], capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        return True, f"opened {app}"
            if shutil.which("xdg-open"):
                result = subprocess.run(["xdg-open", app], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return True, f"opened {app}"
            return False, f"no application called {app!r} was found on PATH"
        except Exception as error:
            return False, f"could not open {app!r}: {type(error).__name__}: {error}"

    def focus_window(self, title: str) -> Tuple[bool, str]:
        """Bring a window matching *title* to the front."""
        if self.config.safety.dry_run:
            return True, f"[dry run] would focus {title}"
        platform = sys.platform
        if platform.startswith("win"):
            found = self._windows_focus(title)
            return (True, f"switched to {title}") if found else (False, f"no open window matches {title!r}")
        if platform.startswith("darwin"):
            script = f'tell application "System Events" to set frontmost of (first process whose name contains "{title}") to true'
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return True, f"switched to {title}"
            return False, f"could not focus {title!r}: {result.stderr.strip()}"
        if shutil.which("wmctrl"):
            result = subprocess.run(["wmctrl", "-a", title], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return True, f"switched to {title}"
        if shutil.which("xdotool"):
            search = subprocess.run(["xdotool", "search", "--name", title], capture_output=True, text=True, timeout=10)
            window_ids = [line for line in search.stdout.split() if line.strip()]
            if window_ids:
                subprocess.run(["xdotool", "windowactivate", window_ids[-1]], capture_output=True, timeout=10)
                return True, f"switched to {title}"
        return False, f"could not find a window matching {title!r}"

    @staticmethod
    def _windows_focus(title: str) -> bool:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        needle = title.lower()
        match = {"handle": 0}

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(handle, _param):
            if not user32.IsWindowVisible(handle):
                return True
            length = user32.GetWindowTextLengthW(handle)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, buffer, length + 1)
            if needle in buffer.value.lower():
                match["handle"] = handle
                return False
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        handle = match["handle"]
        if not handle:
            return False
        user32.ShowWindow(handle, 9)  # SW_RESTORE
        user32.SetForegroundWindow(handle)
        return True

    # --- clipboard --------------------------------------------------------
    def clipboard_text(self) -> str:
        """Read the clipboard using whichever mechanism exists."""
        for reader in (self._clipboard_qt, self._clipboard_tk, self._clipboard_cli):
            try:
                text = reader()
                if text is not None:
                    return text
            except Exception:
                continue
        return ""

    def set_clipboard_text(self, text: str) -> bool:
        for writer in (self._clipboard_qt_set, self._clipboard_cli_set):
            try:
                if writer(text):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _clipboard_qt() -> Optional[str]:
        QtWidgets = lazy.optional("PySide6.QtWidgets", attr="QApplication")
        if QtWidgets is None or QtWidgets.instance() is None:
            return None
        return QtWidgets.clipboard().text()

    @staticmethod
    def _clipboard_qt_set(text: str) -> bool:
        QtWidgets = lazy.optional("PySide6.QtWidgets", attr="QApplication")
        if QtWidgets is None or QtWidgets.instance() is None:
            return False
        QtWidgets.clipboard().setText(text)
        return True

    @staticmethod
    def _clipboard_tk() -> Optional[str]:
        tkinter = lazy.optional("tkinter")
        if tkinter is None:
            return None
        root = tkinter.Tk()
        root.withdraw()
        try:
            return root.clipboard_get()
        except Exception:
            return ""
        finally:
            root.destroy()

    @staticmethod
    def _clipboard_cli() -> Optional[str]:
        if sys.platform.startswith("darwin"):
            return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5).stdout
        for tool, args in (("xclip", ["-selection", "clipboard", "-o"]), ("xsel", ["-b"]), ("wl-paste", [])):
            if shutil.which(tool):
                return subprocess.run([tool, *args], capture_output=True, text=True, timeout=5).stdout
        if sys.platform.startswith("win"):
            return subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True, text=True, timeout=10).stdout
        return None

    @staticmethod
    def _clipboard_cli_set(text: str) -> bool:
        if sys.platform.startswith("darwin"):
            process = subprocess.run(["pbcopy"], input=text, text=True, timeout=5)
            return process.returncode == 0
        for tool, args in (("xclip", ["-selection", "clipboard"]), ("xsel", ["-b", "-i"]), ("wl-copy", [])):
            if shutil.which(tool):
                process = subprocess.run([tool, *args], input=text, text=True, timeout=5)
                return process.returncode == 0
        if sys.platform.startswith("win"):
            process = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                input=text,
                text=True,
                timeout=10,
            )
            return process.returncode == 0
        return False

    # --- reporting --------------------------------------------------------
    def describe_state(self) -> Dict[str, Any]:
        window = active_window()
        return {
            "input_backends": list(self.input.backend_names),
            "input_backend": self.input.backend_name,
            "dry_run": self.config.safety.dry_run,
            "active_window": window.describe(),
            "primary_monitor": primary_monitor(monitors_or_default()).as_dict(),
        }
