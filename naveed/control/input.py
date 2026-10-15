"""Mouse and keyboard control, with a backend chain and human-like motion.

The backends exist because no single library is available everywhere:

``pynput``     best cross-platform speech-free input, needs X11/Wayland portal,
               macOS Accessibility, or Windows (works everywhere it installs).
``pyautogui``  very common, slightly slower, good Windows/macOS fallback.
``win32``      pure ``ctypes`` ``SendInput``: works on locked-down Windows boxes
               where nothing can be pip-installed.
``xdotool``    pure CLI last resort on Linux.

Everything is imported inside the backend that needs it (:mod:`naveed.lazy`), so
Naveed starts with none of them installed and still shows its mascot.

Mouse motion is interpolated rather than teleported: an eased path with a small
amount of jitter is what makes an automation feel like a fingertip instead of a
laser, and it also gives the target application time to register hover states
before the click lands.
"""

from __future__ import annotations

import math
import random
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import lazy
from .keys import normalize_key, normalize_modifiers, parse_hotkey

__all__ = [
    "InputBackend",
    "InputController",
    "InputError",
    "PynputBackend",
    "PyAutoGUIBackend",
    "WindowsBackend",
    "XdotoolBackend",
    "available_backends",
]

MAX_SCROLL = 4000


class InputError(RuntimeError):
    """No input backend could carry out the request."""


# --- backends ---------------------------------------------------------------

class InputBackend:
    """Minimal surface every backend implements."""

    name = "backend"
    #: Some backends cannot press keys while the display is asleep etc.
    supports_typing = True

    def available(self) -> bool:
        raise NotImplementedError

    def move_to(self, x: int, y: int) -> None: raise NotImplementedError
    def click(self, button: str = "left", count: int = 1) -> None: raise NotImplementedError
    def press(self, button: str = "left") -> None: raise NotImplementedError
    def release(self, button: str = "left") -> None: raise NotImplementedError
    def scroll(self, dx: int, dy: int) -> None: raise NotImplementedError
    def type_text(self, text: str) -> None: raise NotImplementedError
    def press_key(self, key: str, modifiers: Sequence[str] = ()) -> None: raise NotImplementedError
    def key_down(self, key: str) -> None: raise NotImplementedError
    def key_up(self, key: str) -> None: raise NotImplementedError
    def position(self) -> Optional[Tuple[int, int]]: return None


class PynputBackend(InputBackend):
    """``pynput`` — the default when installed."""

    name = "pynput"

    def available(self) -> bool:
        return lazy.find_spec_safe("pynput") is not None

    # --- wiring -------------------------------------------------------
    def _mouse(self):
        return lazy.load("pynput.mouse")

    def _keyboard(self):
        return lazy.load("pynput.keyboard")

    @staticmethod
    def _button(mouse_module, name: str):
        mapping = {
            "left": mouse_module.Button.left,
            "right": mouse_module.Button.right,
            "middle": mouse_module.Button.middle,
        }
        return mapping.get((name or "left").lower(), mouse_module.Button.left)

    def _key(self, name: str):
        keyboard = self._keyboard()
        specials = {
            "Enter": keyboard.Key.enter,
            "Escape": keyboard.Key.esc,
            "Tab": keyboard.Key.tab,
            "Space": keyboard.Key.space,
            "Backspace": keyboard.Key.backspace,
            "Delete": keyboard.Key.delete,
            "Insert": keyboard.Key.insert,
            "Home": keyboard.Key.home,
            "End": keyboard.Key.end,
            "PageUp": keyboard.Key.page_up,
            "PageDown": keyboard.Key.page_down,
            "ArrowUp": keyboard.Key.up,
            "ArrowDown": keyboard.Key.down,
            "ArrowLeft": keyboard.Key.left,
            "ArrowRight": keyboard.Key.right,
            "CapsLock": keyboard.Key.caps_lock,
            "PrintScreen": keyboard.Key.print_screen,
            "Shift": keyboard.Key.shift,
            "Control": keyboard.Key.ctrl,
            "Alt": keyboard.Key.alt,
            "Meta": getattr(keyboard.Key, "cmd", None) or getattr(keyboard.Key, "cmd_l", keyboard.Key.ctrl),
        }
        if name in specials and specials[name] is not None:
            return specials[name]
        if len(name) == 1:
            return name
        lowered = name.lower()
        if lowered in ("f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"):
            return getattr(keyboard.Key, lowered)
        return name

    # --- actions ------------------------------------------------------
    def move_to(self, x: int, y: int) -> None:
        self._mouse().Controller().position = (int(x), int(y))

    def click(self, button: str = "left", count: int = 1) -> None:
        mouse = self._mouse()
        controller = mouse.Controller()
        controller.click(self._button(mouse, button), count)
        if count > 1:
            # pynput's multi-click is not always honoured by every app.
            for _ in range(count - 1):
                controller.click(self._button(mouse, button))

    def press(self, button: str = "left") -> None:
        mouse = self._mouse()
        mouse.Controller().press(self._button(mouse, button))

    def release(self, button: str = "left") -> None:
        mouse = self._mouse()
        mouse.Controller().release(self._button(mouse, button))

    def scroll(self, dx: int, dy: int) -> None:
        self._mouse().Controller().scroll(int(dx), int(dy))

    def type_text(self, text: str) -> None:
        self._keyboard().Controller().type(text)

    def press_key(self, key: str, modifiers: Sequence[str] = ()) -> None:
        keyboard = self._keyboard()
        controller = keyboard.Controller()
        pressed = []
        try:
            for modifier in modifiers:
                resolved = self._key(normalize_key(modifier))
                controller.press(resolved)
                pressed.append(resolved)
            controller.press(self._key(key))
            controller.release(self._key(key))
        finally:
            for resolved in reversed(pressed):
                controller.release(resolved)

    def key_down(self, key: str) -> None:
        self._keyboard().Controller().press(self._key(normalize_key(key)))

    def key_up(self, key: str) -> None:
        self._keyboard().Controller().release(self._key(normalize_key(key)))

    def position(self) -> Optional[Tuple[int, int]]:
        return tuple(self._mouse().Controller().position)  # type: ignore[return-value]


class PyAutoGUIBackend(InputBackend):
    """``pyautogui`` fallback."""

    name = "pyautogui"

    def available(self) -> bool:
        return lazy.find_spec_safe("pyautogui") is not None

    def _gui(self):
        gui = lazy.load("pyautogui")
        gui.FAILSAFE = False
        gui.PAUSE = 0.01
        return gui

    def move_to(self, x: int, y: int) -> None:
        self._gui().moveTo(int(x), int(y), duration=0)

    def click(self, button: str = "left", count: int = 1) -> None:
        self._gui().click(button=(button or "left").lower(), clicks=max(1, count), interval=0.06)

    def press(self, button: str = "left") -> None:
        self._gui().mouseDown(button=(button or "left").lower())

    def release(self, button: str = "left") -> None:
        self._gui().mouseUp(button=(button or "left").lower())

    def scroll(self, dx: int, dy: int) -> None:
        gui = self._gui()
        if dy:
            gui.scroll(int(dy))
        if dx:
            gui.hscroll(int(dx))

    def type_text(self, text: str) -> None:
        self._gui().typewrite(text, interval=0.012)

    def press_key(self, key: str, modifiers: Sequence[str] = ()) -> None:
        gui = self._gui()
        resolved = normalize_key(key)
        mapped = {"Enter": "enter", "Escape": "esc", "Control": "ctrl", "Meta": "win", "ArrowUp": "up",
                  "ArrowDown": "down", "ArrowLeft": "left", "ArrowRight": "right", "PageUp": "pageup",
                  "PageDown": "pagedown", "Delete": "delete", "Backspace": "backspace", "Tab": "tab",
                  "Space": "space"}.get(resolved, resolved)
        combo = [mod.lower() for mod in modifiers] + [mapped]
        gui.hotkey(*combo) if len(combo) > 1 else gui.press(mapped)

    def key_down(self, key: str) -> None:
        self._gui().keyDown(normalize_key(key).lower())

    def key_up(self, key: str) -> None:
        self._gui().keyUp(normalize_key(key).lower())

    def position(self) -> Optional[Tuple[int, int]]:
        return tuple(self._gui().position())  # type: ignore[return-value]


class WindowsBackend(InputBackend):
    """Pure ``ctypes`` ``SendInput``: no third-party input library at all.

    This is the safety net for locked-down Windows machines where an agent still
    has to work; it needs nothing installed beyond Python itself.
    """

    name = "win32"

    # --- constants ----------------------------------------------------
    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE = 0x0001, 0x8000
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
    MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
    MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
    MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004

    _VK = {
        "Enter": 0x0D, "Escape": 0x1B, "Tab": 0x09, "Space": 0x20, "Backspace": 0x08,
        "Delete": 0x2E, "Insert": 0x2D, "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
        "ArrowUp": 0x26, "ArrowDown": 0x28, "ArrowLeft": 0x25, "ArrowRight": 0x27,
        "Shift": 0x10, "Control": 0x11, "Alt": 0x12, "Meta": 0x5B, "CapsLock": 0x14,
        **{f"F{index}": 0x6F + index for index in range(1, 13)},
    }

    def available(self) -> bool:
        return sys.platform.startswith("win")

    def _user32(self):
        import ctypes

        return ctypes.windll.user32

    def _send_mouse(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
        import ctypes
        from ctypes import wintypes

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT(ctypes.Structure):
            class _UNION(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT)]
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]

        entry = INPUT(type=self.INPUT_MOUSE)
        entry.mi = MOUSEINPUT(dx, dy, data, flags, 0, None)
        self._user32().SendInput(1, ctypes.byref(entry), ctypes.sizeof(INPUT))

    def move_to(self, x: int, y: int) -> None:
        user32 = self._user32()
        self._send_mouse(self.MOUSEEVENTF_MOVE | self.MOUSEEVENTF_ABSOLUTE, *self._absolute(user32, x, y))

    @staticmethod
    def _absolute(user32, x: int, y: int) -> Tuple[int, int]:

        width = user32.GetSystemMetrics(78) or user32.GetSystemMetrics(0)   # virtual screen
        height = user32.GetSystemMetrics(79) or user32.GetSystemMetrics(1)
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        nx = int((int(x) - left) * 65535 / max(1, width - 1))
        ny = int((int(y) - top) * 65535 / max(1, height - 1))
        return nx, ny

    def click(self, button: str = "left", count: int = 1) -> None:
        down, up = {
            "right": (self.MOUSEEVENTF_RIGHTDOWN, self.MOUSEEVENTF_RIGHTUP),
            "middle": (self.MOUSEEVENTF_MIDDLEDOWN, self.MOUSEEVENTF_MIDDLEUP),
        }.get((button or "left").lower(), (self.MOUSEEVENTF_LEFTDOWN, self.MOUSEEVENTF_LEFTUP))
        for _ in range(max(1, count)):
            self._send_mouse(down)
            time.sleep(0.02)
            self._send_mouse(up)
            time.sleep(0.05)

    def press(self, button: str = "left") -> None:
        down = {"right": self.MOUSEEVENTF_RIGHTDOWN, "middle": self.MOUSEEVENTF_MIDDLEDOWN}.get(
            (button or "left").lower(), self.MOUSEEVENTF_LEFTDOWN
        )
        self._send_mouse(down)

    def release(self, button: str = "left") -> None:
        up = {"right": self.MOUSEEVENTF_RIGHTUP, "middle": self.MOUSEEVENTF_MIDDLEUP}.get(
            (button or "left").lower(), self.MOUSEEVENTF_LEFTUP
        )
        self._send_mouse(up)

    def scroll(self, dx: int, dy: int) -> None:
        if dy:
            self._send_mouse(self.MOUSEEVENTF_WHEEL, data=int(dy) * 120)
        if dx:
            self._send_mouse(self.MOUSEEVENTF_HWHEEL, data=int(dx) * 120)

    def _send_key(self, vk: int, *, up: bool = False, scan: int = 0, unicode_mode: bool = False) -> None:
        import ctypes
        from ctypes import wintypes

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT(ctypes.Structure):
            class _UNION(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]

        flags = self.KEYEVENTF_KEYUP if up else 0
        if unicode_mode:
            flags |= self.KEYEVENTF_UNICODE
        entry = INPUT(type=self.INPUT_KEYBOARD)
        entry.ki = KEYBDINPUT(0 if unicode_mode else vk, scan, flags, 0, None)
        self._user32().SendInput(1, ctypes.byref(entry), ctypes.sizeof(INPUT))

    def type_text(self, text: str) -> None:
        # Unicode injection types any script, regardless of the keyboard layout.
        for char in text:
            code = ord(char)
            if char == "\n":
                self.press_key("Enter")
                continue
            if char == "\t":
                self.press_key("Tab")
                continue
            self._send_key(0, scan=code, unicode_mode=True)
            self._send_key(0, up=True, scan=code, unicode_mode=True)
            time.sleep(0.004)

    def _vk_for(self, key: str) -> int:
        resolved = normalize_key(key)
        if resolved in self._VK:
            return self._VK[resolved]
        if len(resolved) == 1:
            return ord(resolved.upper())
        return 0

    def press_key(self, key: str, modifiers: Sequence[str] = ()) -> None:
        codes = [self._vk_for(modifier) for modifier in modifiers]
        target = self._vk_for(key)
        for code in codes:
            if code:
                self._send_key(code)
        if target:
            self._send_key(target)
            self._send_key(target, up=True)
        for code in reversed(codes):
            if code:
                self._send_key(code, up=True)

    def key_down(self, key: str) -> None:
        code = self._vk_for(key)
        if code:
            self._send_key(code)

    def key_up(self, key: str) -> None:
        code = self._vk_for(key)
        if code:
            self._send_key(code, up=True)


class XdotoolBackend(InputBackend):
    """Last-resort Linux CLI backend (``xdotool``)."""

    name = "xdotool"

    def available(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        return bool(shutil.which("xdotool")) and bool(
            __import__("os").environ.get("DISPLAY")
        )

    def _run(self, *args: str) -> None:
        subprocess.run(["xdotool", *args], check=False, capture_output=True, timeout=5)

    def move_to(self, x: int, y: int) -> None:
        self._run("mousemove", str(int(x)), str(int(y)))

    def click(self, button: str = "left", count: int = 1) -> None:
        self._run("click", "--repeat", str(max(1, count)), {"right": "3", "middle": "2"}.get(
            (button or "left").lower(), "1"
        ))

    def press(self, button: str = "left") -> None:
        self._run("mousedown", {"right": "3", "middle": "2"}.get((button or "left").lower(), "1"))

    def release(self, button: str = "left") -> None:
        self._run("mouseup", {"right": "3", "middle": "2"}.get((button or "left").lower(), "1"))

    def scroll(self, dx: int, dy: int) -> None:
        if dy > 0:
            self._run("click", "--repeat", str(min(40, int(dy))), "5")
        elif dy < 0:
            self._run("click", "--repeat", str(min(40, int(-dy))), "4")
        if dx > 0:
            self._run("click", "--repeat", str(min(40, int(dx))), "7")
        elif dx < 0:
            self._run("click", "--repeat", str(min(40, int(-dx))), "6")

    def type_text(self, text: str) -> None:
        self._run("type", "--clearmodifiers", "--delay", "12", text)

    def press_key(self, key: str, modifiers: Sequence[str] = ()) -> None:
        resolved = normalize_key(key)
        combo = "+".join([*(mod.lower() for mod in modifiers), resolved.lower()])
        self._run("key", "--clearmodifiers", combo)

    def key_down(self, key: str) -> None:
        self._run("keydown", normalize_key(key).lower())

    def key_up(self, key: str) -> None:
        self._run("keyup", normalize_key(key).lower())


def available_backends() -> List[InputBackend]:
    """Usable input backends in preference order."""
    backends: List[InputBackend] = [PynputBackend(), PyAutoGUIBackend(), WindowsBackend(), XdotoolBackend()]
    result: List[InputBackend] = []
    for backend in backends:
        try:
            if backend.available():
                result.append(backend)
        except Exception:
            continue
    return result


# --- controller -------------------------------------------------------------

class InputController:
    """High-level mouse/keyboard control on top of the backend chain.

    Notable behaviour:

    * :meth:`move_to` eases in and adds a little jitter, so applications register
      hover/highlight states before the click arrives.
    * :meth:`click_at` calls the optional ``before_pointer`` hook, which the
      overlay uses to make itself click-through — otherwise a mascot sitting on
      the target pixel would swallow the agent's own click.
    * typing is chunked, so a long paste does not appear as one instantaneous
      block of characters to applications that debounce input.
    """

    def __init__(
        self,
        *,
        backends: Optional[Sequence[InputBackend]] = None,
        humanize: bool = True,
        move_duration: float = 0.28,
        jitter: float = 0.9,
        before_pointer: Optional[Any] = None,
        after_pointer: Optional[Any] = None,
        dry_run: bool = False,
    ) -> None:
        self._backends = list(backends) if backends is not None else available_backends()
        self._last_used: Optional[InputBackend] = None
        self.humanize = humanize
        self.move_duration = max(0.0, move_duration)
        self.jitter = max(0.0, jitter)
        self.before_pointer = before_pointer
        self.after_pointer = after_pointer
        self.dry_run = dry_run
        self._random = random.Random()

    # --- backend plumbing ---------------------------------------------
    def refresh(self) -> "InputController":
        self._backends = available_backends()
        return self

    @property
    def backends(self) -> Sequence[InputBackend]:
        return tuple(self._backends)

    @property
    def backend_name(self) -> str:
        if self._last_used is not None:
            return self._last_used.name
        return self._backends[0].name if self._backends else "none"

    @property
    def available(self) -> bool:
        return bool(self._backends)

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Invoke *method* on the first backend that accepts it."""
        if self.dry_run:
            self.last_action = {"method": method, "args": args, "kwargs": kwargs, "dry_run": True}
            return None
        errors: List[str] = []
        for backend in self._ordered():
            try:
                result = getattr(backend, method)(*args, **kwargs)
                self._last_used = backend
                self.last_action = {"method": method, "args": args, "kwargs": kwargs, "via": backend.name}
                return result
            except NotImplementedError:
                continue
            except Exception as error:
                errors.append(f"{backend.name}: {type(error).__name__}: {error}")
                continue
        raise InputError(
            "No input backend could perform "
            f"'{method}'. Tried: {', '.join(self.backend_names) or 'none'}. "
            + ("; ".join(errors) if errors else "Install the 'input' extra: pynput.")
        )

    last_action: Optional[Dict[str, Any]] = None

    def _ordered(self) -> List[InputBackend]:
        if self._last_used is None:
            return list(self._backends)
        return [self._last_used] + [backend for backend in self._backends if backend is not self._last_used]

    @property
    def backend_names(self) -> List[str]:
        return [backend.name for backend in self._backends]

    # --- pointer -------------------------------------------------------
    def position(self) -> Optional[Tuple[int, int]]:
        if not self._backends:
            return None
        try:
            return self._call("position")
        except InputError:
            return None

    def move_to(self, x: float, y: float, *, duration: Optional[float] = None) -> None:
        """Move the pointer, easing along a slightly jittered path."""
        target_x, target_y = int(round(x)), int(round(y))
        start = self.position() if self.humanize else None
        span = self.move_duration if duration is None else max(0.0, duration)
        if not self.humanize or start is None or span <= 0.02:
            self._call("move_to", target_x, target_y)
            return

        distance = math.hypot(target_x - start[0], target_y - start[1])
        steps = max(3, min(26, int(distance / 26) + 3))
        for index in range(1, steps + 1):
            progress = index / steps
            # ease-in-out so the pointer accelerates and settles like a hand.
            eased = progress * progress * (3.0 - 2.0 * progress)
            px = start[0] + (target_x - start[0]) * eased
            py = start[1] + (target_y - start[1]) * eased
            if index < steps and self.jitter > 0:
                px += self._random.uniform(-self.jitter, self.jitter)
                py += self._random.uniform(-self.jitter, self.jitter)
            try:
                self._call("move_to", int(round(px)), int(round(py)))
            except InputError:
                break
            time.sleep(max(0.002, span / steps))

    def click_at(
        self,
        x: float,
        y: float,
        *,
        button: str = "left",
        count: int = 1,
        settle: float = 0.06,
        move: bool = True,
    ) -> None:
        """Move (optionally) and click, with the pointer hooks run around it."""
        self._pointer_context(True)
        try:
            if move:
                self.move_to(x, y)
            else:
                self._call("move_to", int(round(x)), int(round(y)))
            if settle:
                time.sleep(settle)
            self._call("click", button=button, count=max(1, int(count)))
            time.sleep(0.04)
        finally:
            self._pointer_context(False)

    def drag(
        self,
        path: Sequence[Tuple[int, int]],
        *,
        button: str = "left",
        duration: float = 0.5,
    ) -> None:
        """Press, glide through *path*, release (port of brah's drag action)."""
        if len(path) < 2:
            raise ValueError("Drag path must contain at least two points.")
        self._pointer_context(True)
        try:
            self.move_to(path[0][0], path[0][1])
            self._call("press", button=button)
            segment = max(0.02, duration / max(1, len(path) - 1))
            for point in path[1:]:
                self.move_to(point[0], point[1], duration=segment)
            self._call("release", button=button)
        finally:
            self._pointer_context(False)

    def scroll(self, dy: int, *, dx: int = 0, x: Optional[float] = None, y: Optional[float] = None) -> None:
        """Scroll at (optionally) a position, in pixel-units where supported."""
        clamped_y = max(-MAX_SCROLL, min(MAX_SCROLL, int(dy)))
        clamped_x = max(-MAX_SCROLL, min(MAX_SCROLL, int(dx)))
        self._pointer_context(True)
        try:
            if x is not None and y is not None:
                self.move_to(x, y, duration=0.15)
            # Wheel deltas are logical notches for most backends.
            notches_y = int(round(clamped_y / 100.0)) or (1 if clamped_y > 0 else (-1 if clamped_y < 0 else 0))
            notches_x = int(round(clamped_x / 100.0)) or (1 if clamped_x > 0 else (-1 if clamped_x < 0 else 0))
            self._call("scroll", notches_x, notches_y)
        finally:
            self._pointer_context(False)

    # --- keyboard ------------------------------------------------------
    def type_text(self, text: str, *, chunk: int = 220, interval: float = 0.02) -> None:
        if not text:
            return
        for start in range(0, len(text), max(20, chunk)):
            self._call("type_text", text[start:start + max(20, chunk)])
            time.sleep(interval)

    def press_key(self, key: str, modifiers: Sequence[str] = ()) -> None:
        resolved = normalize_key(key)
        mods = normalize_modifiers(modifiers)
        self._call("press_key", resolved, mods)

    def hotkey(self, hotkey: str) -> None:
        """Press a chord such as ``"ctrl+shift+t"``."""
        parts = parse_hotkey(hotkey)
        if not parts:
            return
        *modifiers, key = parts
        self._call("press_key", key, tuple(modifiers))

    def key_down(self, key: str) -> None:
        self._call("key_down", normalize_key(key))

    def key_up(self, key: str) -> None:
        self._call("key_up", normalize_key(key))

    # --- hooks ---------------------------------------------------------
    def _pointer_context(self, entering: bool) -> None:
        hook = self.before_pointer if entering else self.after_pointer
        if hook is None:
            return
        try:
            hook()
        except Exception:
            pass
