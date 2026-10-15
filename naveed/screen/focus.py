"""Which app is in front right now, and where is its window.

The window-focus half of **voice-computer-use-agent**
(https://github.com/jarmen423/voice-computer-use-agent, MIT) —
``voiceuse/os_controller.py::list_windows``/``find_window`` — showed that naming
the *active application* is what makes an agent's screenshots interpretable
("VS Code, unsaved buffer" beats "a dark rectangle").  Naveed needs the same for
its world model, and needs the window rectangle so it can capture only the
monitor showing that window.

Windows uses ``ctypes`` straight against user32 (no pywin32 required); macOS uses
Quartz when pyobjc is present; Linux shells out to ``xdotool``/``wmctrl`` when
they exist, and degrades to ``None`` instead of failing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .. import lazy
from .displays import Monitor, Rect, monitor_for_rect

__all__ = ["ActiveWindow", "active_window", "list_windows"]


@dataclass(frozen=True)
class ActiveWindow:
    """The foreground window: title, owning process and geometry."""

    title: str = ""
    process: str = ""
    pid: int = 0
    rect: Optional[Rect] = None
    handle: int = 0

    @property
    def app(self) -> str:
        """Short app label used in prompts and logs."""
        if self.process:
            return self.process
        return self.title.split(" - ")[-1] if " - " in self.title else (self.title or "unknown")

    def monitor(self, monitors: Optional[Sequence[Monitor]] = None) -> Monitor:
        """The monitor showing most of this window (falls back to primary)."""
        if self.rect is None:
            from .displays import primary_monitor

            return primary_monitor(monitors)
        return monitor_for_rect(self.rect, monitors)

    def describe(self) -> str:
        if not self.title and not self.process:
            return "unknown foreground window"
        parts = [part for part in (self.process, self.title) if part]
        label = " - ".join(dict.fromkeys(parts))
        if self.rect:
            label += f" [{self.rect[2]}x{self.rect[3]} at {self.rect[0]},{self.rect[1]}]"
        return label

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "process": self.process,
            "pid": self.pid,
            "rect": list(self.rect) if self.rect else None,
            "handle": self.handle,
        }


# --- Windows (ctypes, no pywin32) -------------------------------------------

def _windows_active_window() -> ActiveWindow:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    handle = user32.GetForegroundWindow()
    if not handle:
        return ActiveWindow()

    length = user32.GetWindowTextLengthW(handle)
    buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    user32.GetWindowTextW(handle, buffer, length + 1)

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))

    process = ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if kernel:
        try:
            size = wintypes.DWORD(32768)
            path_buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(kernel, 0, path_buffer, ctypes.byref(size)):
                process = os.path.basename(path_buffer.value)
        finally:
            kernel32.CloseHandle(kernel)

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    rect = RECT()
    geometry = None
    if user32.GetWindowRect(handle, ctypes.byref(rect)):
        geometry = (int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top))

    return ActiveWindow(
        title=buffer.value or "",
        process=process,
        pid=int(pid.value),
        rect=geometry,
        handle=int(handle),
    )


# --- macOS -------------------------------------------------------------------

def _darwin_active_window() -> ActiveWindow:
    quartz = lazy.optional("Quartz")
    if quartz is None:
        return ActiveWindow()
    try:
        options = quartz.kCGWindowListOptionOnScreenOnly | quartz.kCGWindowListExcludeDesktopElements
        windows = quartz.CGWindowListCopyWindowInfo(options, quartz.kCGNullWindowID) or []
    except Exception:
        return ActiveWindow()
    for entry in windows:
        try:
            layer = int(entry.get("kCGWindowLayer", 1))
            bounds = entry.get("kCGWindowBounds") or {}
            if layer != 0 or float(bounds.get("Height", 0)) < 40:
                continue
            return ActiveWindow(
                title=str(entry.get("kCGWindowName") or ""),
                process=str(entry.get("kCGWindowOwnerName") or ""),
                pid=int(entry.get("kCGWindowOwnerPID") or 0),
                rect=(
                    int(bounds.get("X", 0)),
                    int(bounds.get("Y", 0)),
                    int(bounds.get("Width", 0)),
                    int(bounds.get("Height", 0)),
                ),
                handle=int(entry.get("kCGWindowNumber") or 0),
            )
        except (TypeError, ValueError):
            continue
    return ActiveWindow()


# --- Linux (xdotool / wmctrl) -----------------------------------------------

def _linux_active_window() -> ActiveWindow:
    xdotool = shutil.which("xdotool")
    if xdotool:
        try:
            window_id = subprocess.run(
                [xdotool, "getactivewindow"], capture_output=True, text=True, timeout=2
            ).stdout.strip()
            if window_id:
                title = subprocess.run(
                    [xdotool, "getwindowname", window_id], capture_output=True, text=True, timeout=2
                ).stdout.strip()
                geometry = subprocess.run(
                    [xdotool, "getwindowgeometry", "--shell", window_id], capture_output=True, text=True, timeout=2
                ).stdout
                values = {}
                for line in geometry.splitlines():
                    if "=" in line:
                        key, _, value = line.partition("=")
                        values[key.strip()] = value.strip()
                rect = None
                if {"X", "Y", "WIDTH", "HEIGHT"} <= set(values):
                    rect = (int(values["X"]), int(values["Y"]), int(values["WIDTH"]), int(values["HEIGHT"]))
                pid_text = subprocess.run(
                    [xdotool, "getwindowpid", window_id], capture_output=True, text=True, timeout=2
                ).stdout.strip()
                return ActiveWindow(
                    title=title,
                    process=_process_name(pid_text),
                    pid=int(pid_text or 0),
                    rect=rect,
                    handle=int(window_id or 0),
                )
        except (subprocess.SubprocessError, ValueError, OSError):
            pass

    wmctrl = shutil.which("wmctrl")
    if wmctrl:
        try:
            output = subprocess.run([wmctrl, "-l", "-p"], capture_output=True, text=True, timeout=2).stdout
            for line in output.splitlines():
                parts = line.split(None, 4)
                if len(parts) < 5:
                    continue
                return ActiveWindow(title=parts[4], pid=int(parts[2]), process=_process_name(parts[2]))
        except (subprocess.SubprocessError, ValueError, OSError):
            pass
    return ActiveWindow()


def _process_name(pid_text: str) -> str:
    try:
        pid = int(pid_text)
    except (TypeError, ValueError):
        return ""
    try:
        with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


# --- public API --------------------------------------------------------------

def active_window(*, platform: Optional[str] = None) -> ActiveWindow:
    """Best-effort foreground window, never raising."""
    platform = platform or sys.platform
    try:
        if platform.startswith("win"):
            return _windows_active_window()
        if platform.startswith("darwin"):
            return _darwin_active_window()
        if platform.startswith("linux"):
            return _linux_active_window()
    except Exception:
        return ActiveWindow()
    return ActiveWindow()


def list_windows(*, platform: Optional[str] = None, limit: int = 40) -> List[ActiveWindow]:
    """Open windows, most-recently-used first where the platform allows it.

    Windows: enumerates top-level windows via EnumWindows.  Linux/macOS: returns
    the active window only — enough for the world model, and deliberately cheap.
    """
    platform = platform or sys.platform
    if not platform.startswith("win"):
        window = active_window(platform=platform)
        return [window] if window.title or window.process else []

    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover - non-Windows
        return []

    user32 = ctypes.windll.user32
    results: List[ActiveWindow] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(handle: int, _param: int) -> bool:
        if not user32.IsWindowVisible(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        rect = RECT()
        geometry = None
        if user32.GetWindowRect(handle, ctypes.byref(rect)):
            geometry = (int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top))
        results.append(
            ActiveWindow(title=buffer.value, pid=int(pid.value), rect=geometry, handle=int(handle))
        )
        return len(results) < limit

    try:
        user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception:
        return results
    return results
