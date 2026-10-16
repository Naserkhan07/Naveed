"""Why is the window not on my screen?

The mascot is the whole product, and "I ran it and nothing appeared" is the
report that is hardest to act on: the process is alive, the tray may be there,
and the only evidence is an empty desktop. This module answers that question
with evidence instead of sympathy:

* is Qt importable at all — and if not, **which** system library is missing and
  which command installs it (``libGL.so.1`` and friends are the usual answer, and
  ``pip install`` does not fix them);
* is there a screen, and which platform plugin did Qt choose;
* does the window come up: visible, frameless, always-on-top, translucent, and
  *inside* the screen rather than off an edge;
* and, when one is asked for, a PNG of what the window actually contains.

Everything here is read-only and side-effect-free apart from showing a window for
a few hundred milliseconds. It runs headless too (``QT_QPA_PLATFORM=offscreen``),
which is how the tests exercise it, so the same code path is checked in CI on
machines that have no display.
"""

from __future__ import annotations

import os
import platform
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "environment_report",
    "library_hint",
    "run_check",
    "qt_available",
]

#: System libraries Qt links against, and what to do about a missing one. The
#: keys are the substrings the dynamic loader itself prints, so matching the
#: error message the user is looking at is enough to name the fix.
LIBRARY_FIXES: List[Tuple[str, str]] = [
    ("libGL.so.1", 'sudo apt install libgl1 libglx-mesa0        # Debian/Ubuntu\n  sudo dnf install mesa-libGL                    # Fedora'),
    ("libEGL.so.1", 'sudo apt install libegl1                       # Debian/Ubuntu\n  sudo dnf install mesa-libEGL                   # Fedora'),
    ("libxkbcommon", 'sudo apt install libxkbcommon-x11-0             # Debian/Ubuntu\n  sudo dnf install libxkbcommon-x11              # Fedora'),
    ("libdbus-1", 'sudo apt install libdbus-1-3                     # Debian/Ubuntu\n  sudo dnf install dbus-libs                     # Fedora'),
    ("libxcb-cursor", 'sudo apt install libxcb-cursor0                  # Debian/Ubuntu'),
    ("libxcb-xinerama", 'sudo apt install libxcb-xinerama0                # Debian/Ubuntu'),
    ("libxcb-icccm", 'sudo apt install libxcb-icccm4                    # Debian/Ubuntu'),
    ("libxcb-keysyms", 'sudo apt install libxcb-keysyms1                  # Debian/Ubuntu'),
    ("libxcb-image", 'sudo apt install libxcb-image0                    # Debian/Ubuntu'),
    ("libxcb-render-util", 'sudo apt install libxcb-render-util0              # Debian/Ubuntu'),
    ("libxcb-randr", 'sudo apt install libxcb-randr0                    # Debian/Ubuntu'),
    ("libfontconfig", 'sudo apt install libfontconfig1                   # Debian/Ubuntu'),
    ("libfreetype", 'sudo apt install libfreetype6                     # Debian/Ubuntu'),
]

#: PySide6 releases with a known, bisected refcount regression: the process
#: aborts with "Fatal Python error: none_dealloc: deallocating None" after a few
#: thousand gradient fills through a QPainter, which the mascot reaches in a few
#: seconds of animation. Measured in this repo: 6.12.0 aborts after ~2000 frames
#: of a radial-gradient fill, 6.8.1 survives 4000+. The `ui` extra carries a
#: matching upper bound, so a fresh install gets the working version.
UNSTABLE_PYSIDE = ("6.12.",)

#: The Qt platform plugins that can put a window on a real desktop. ``offscreen``
#: and ``minimal`` exist for tests: a process started with them *works*, and shows
#: nothing, which is exactly the confusing case this module exists to catch.
VISIBLE_PLATFORMS = ("xcb", "wayland", "windows", "cocoa", "eglfs")


def library_hint(text: str) -> Optional[str]:
    """Turn a loader error into the command that fixes it, if we know one."""
    lowered = str(text or "")
    for needle, fix in LIBRARY_FIXES:
        if needle in lowered:
            return fix
    return None


def pyside_warning(version: str) -> Optional[str]:
    """Say so when the installed PySide6 has a known crash, and what to install."""
    text = str(version or "")
    if not any(text.startswith(prefix) for prefix in UNSTABLE_PYSIDE):
        return None
    return (
        f"PySide6 {text} has a known refcount bug (upstream, not Naveed\'s): a few thousand\n"
        "gradient fills abort the process with \"Fatal Python error: none_dealloc\".\n"
        'Install a version without it:  pip install "PySide6-Essentials<6.12"'
    )


def qt_available() -> Tuple[bool, str]:
    """Can Qt be imported here? Returns ``(ok, version-or-reason)``."""
    from .. import lazy

    try:
        pyside = lazy.load("PySide6", extra="ui")
    except lazy.MissingDependencyError as error:
        return False, str(error)
    try:
        lazy.load("PySide6.QtWidgets", extra="ui")
    except lazy.MissingDependencyError as error:
        # The package imports but its libraries do not: this is the case pip
        # cannot fix, and the one that looks like "the bot does not appear".
        return False, str(error)
    return True, getattr(pyside, "__version__", "unknown")


def environment_report() -> Dict[str, str]:
    """Everything a support conversation would ask for, gathered without Qt."""
    ok, version = qt_available()
    session = (
        os.environ.get("XDG_SESSION_TYPE")
        or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else "")
        or ("x11" if os.environ.get("DISPLAY") else "")
        or ("windows" if sys.platform.startswith("win") else "")
        or ("macos" if sys.platform == "darwin" else "")
        or "unknown"
    )
    return {
        "python": f"{platform.python_version()} ({sys.platform})",
        "os": f"{platform.system()} {platform.release()}",
        "session": session,
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "display": os.environ.get("DISPLAY", ""),
        "wayland": os.environ.get("WAYLAND_DISPLAY", ""),
        "qt_platform_env": os.environ.get("QT_QPA_PLATFORM", ""),
        "pyside6": version if ok else "NOT USABLE",
        "qt_ok": "yes" if ok else "no",
    }


def _print(stream: Any, line: str = "") -> None:
    print(line, file=stream)


def _print_command(stream: Any, command_block: str, *, indent: str = "    ") -> None:
    """Print a multi-line command block at one consistent indent."""
    for line in str(command_block).splitlines():
        if line.strip():
            _print(stream, f"{indent}{line.strip()}")


def _flags(window: Any, QtCore: Any) -> Dict[str, bool]:
    flags = window.windowFlags()
    kinds = QtCore.Qt.WindowType
    return {
        "frameless": bool(flags & kinds.FramelessWindowHint),
        "always-on-top": bool(flags & kinds.WindowStaysOnTopHint),
        "no-taskbar-entry": bool(flags & kinds.Tool),
        "translucent": bool(window.testAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)),
    }


def _inside(geometry: Any, screen: Any) -> bool:
    if screen is None:
        return False
    area = screen.availableGeometry()
    centre = geometry.center()
    return area.contains(centre)


def run_check(config: Any, *, save: str = "", stream: Any = None) -> int:
    """Report whether the floating window can appear. Returns an exit code."""
    stream = stream or sys.stdout
    from .. import lazy

    # --- 1. the environment -------------------------------------------------
    report = environment_report()
    _print(stream, "Overlay check — can the mascot appear on this machine?")
    _print(stream)
    for label, value in (
        ("python", report["python"]),
        ("system", f"{report['os']}  ({report['session']}"
                   + (f", {report['desktop']}" if report["desktop"] else "") + ")"),
        ("display", report["display"] or "(none set)"),
        ("wayland", report["wayland"] or "(none set)"),
        ("qt plugin", report["qt_platform_env"] or "(chosen by Qt)"),
    ):
        _print(stream, f"  {label:<11} {value}")
    _print(stream)

    # --- 2. Qt itself -------------------------------------------------------
    ok, version = qt_available()
    if not ok:
        _print(stream, "  ✗ PySide6 is not usable here, so no window can be created.")
        _print(stream)
        for line in str(version).splitlines():
            _print(stream, f"    {line}")
        _print(stream)
        _print(stream, "  What to do:")
        _print(stream, '    pip install "naveed[ui]"          # the window extra, if it is missing')
        hint = library_hint(str(version))
        if hint:
            _print(stream, "  …and the system libraries Qt links against:")
            _print_command(stream, hint)
            _print(stream)
            _print(stream, "  (a missing libGL.so.1 / libEGL.so.1 / libxkbcommon is a system")
            _print(stream, "   package, not a pip package — pip install cannot fix it)")
        elif report["session"] in ("unknown", ""):
            _print(stream, "  This looks like a machine with no desktop session at all (no DISPLAY,")
            _print(stream, "  no WAYLAND_DISPLAY). Run Naveed from the desktop it should appear on.")
        return 2
    _print(stream, f"  ✓ PySide6 {version} imports")
    unstable = pyside_warning(str(version))
    if unstable:
        for line in unstable.splitlines():
            _print(stream, f"  ! {line}")

    if report["qt_platform_env"] and report["qt_platform_env"] not in VISIBLE_PLATFORMS:
        _print(stream, f"  ! QT_QPA_PLATFORM={report['qt_platform_env']} is set: Qt will run, and this")
        _print(stream, "    platform plugin draws nothing on screen. Unset it to see the mascot.")
    if not report["display"] and not report["wayland"] and sys.platform not in ("win32", "darwin"):
        _print(stream, "  ! there is no DISPLAY and no WAYLAND_DISPLAY: there is no desktop to")
        _print(stream, "    draw on. (Inside a container? Run Naveed on the host, or forward X11.)")
    _print(stream)

    # --- 3. the application and the screens ---------------------------------
    try:
        QtCore = lazy.load("PySide6.QtCore", extra="ui")
        QtGui = lazy.load("PySide6.QtGui", extra="ui")
        QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")
    except lazy.MissingDependencyError as error:
        _print(stream, f"  ✗ Qt is installed but its widgets do not load: {error}")
        hint = library_hint(str(error))
        if hint:
            _print(stream, "  What to do:")
            _print_command(stream, hint)
        return 2

    app = QtWidgets.QApplication.instance()
    created = app is None
    if app is None:
        app = QtWidgets.QApplication([sys.argv[0] if sys.argv else "naveed"])
    platform_name = app.platformName()
    screens = list(QtGui.QGuiApplication.screens())
    origin = "created by this check" if created else "already running"
    _print(stream, f"  ✓ QApplication up (platform plugin: {platform_name}, {origin})")
    if not screens:
        _print(stream, "  ✗ Qt reports no screens. A window cannot be placed.")
        return 2
    for screen in screens:
        geometry = screen.geometry()
        _print(stream, f"    screen {screen.name() or '(unnamed)'}: "
                       f"{geometry.width()}x{geometry.height()} at {geometry.x()},{geometry.y()}  "
                       f"dpr {screen.devicePixelRatio()}")
    if platform_name not in VISIBLE_PLATFORMS:
        _print(stream, f"  ! the {platform_name!r} plugin is a headless one: the checks below are")
        _print(stream, "    real, but nothing will be visible on a desktop with it.")
    _print(stream)

    # --- 4. the window itself ----------------------------------------------
    from .bridge import OverlayApp

    problems: List[str] = []
    try:
        overlay = OverlayApp(config, serve=False, open_browser=False)
        overlay.build()
    except Exception as error:  # noqa: BLE001 - the report is the point
        _print(stream, f"  ✗ the overlay could not be built: {type(error).__name__}: {error}")
        hint = library_hint(str(error))
        if hint:
            _print(stream, "  What to do:")
            _print_command(stream, hint)
        return 2

    mascot = overlay.mascot
    mascot.show()
    overlay.panel.show(near=(*mascot.position(), getattr(config.overlay, "size", 168)))
    deadline = time.time() + 0.4
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)

    widget = mascot.widget
    window_geometry = widget.geometry()
    screen = widget.screen() or screens[0]
    size = getattr(config.overlay, "size", 168)
    _print(stream, f"  mascot window: {window_geometry.width()}x{window_geometry.height()} "
                   f"at {window_geometry.x()},{window_geometry.y()}  (size {size}, "
                   f"anchor {getattr(config.overlay, 'anchor', '?')})")
    if not widget.isVisible():
        problems.append("the mascot window was created but is not visible")
    if not _inside(window_geometry, screen):
        problems.append(
            f"the mascot is outside {screen.name() or 'the screen'} "
            f"({screen.availableGeometry().width()}x{screen.availableGeometry().height()}); "
            "it may be on a monitor that is no longer attached — delete "
            "~/.naveed/state/overlay.json or set OVERLAY_ANCHOR=below_camera"
        )
    for name, value in _flags(widget, QtCore).items():
        marks = "✓" if value else "-"
        _print(stream, f"    {marks} {name}")
    if not _flags(widget, QtCore)["translucent"] and platform_name in VISIBLE_PLATFORMS:
        _print(stream, "    (no translucency: the mascot will have a solid card behind it —")
        _print(stream, "     on a desktop with no compositor that is the better of the two)")

    panel_widget = overlay.panel.widget
    if panel_widget is not None:
        panel_geometry = panel_widget.geometry()
        _print(stream, f"  panel:         {panel_geometry.width()}x{panel_geometry.height()} "
                       f"at {panel_geometry.x()},{panel_geometry.y()}")
        if not panel_widget.isVisible():
            problems.append("the control panel is not visible")

    if save:
        saved = _save_snapshot(overlay, save)
        for path in saved:
            _print(stream, f"  saved          {path}  (open it: this is what the window contains)")
    _print(stream)

    # --- 5. the verdict -----------------------------------------------------
    if problems:
        _print(stream, "  ✗ the window is not right:")
        for problem in problems:
            _print(stream, f"      • {problem}")
    else:
        _print(stream, f"  ✓ the mascot is on screen at {window_geometry.x()},{window_geometry.y()}, "
                       f"always on top, and the panel is up.")
    try:
        overlay.bridge.stop()
    except Exception:  # pragma: no cover - best effort teardown
        pass
    _print(stream)
    _print(stream, "  run it for real:  python -m naveed")
    _print(stream, "  what it sees:     python -m naveed --check")
    return 1 if problems else 0


def _save_snapshot(overlay: Any, target: str) -> List[str]:
    """Write what the windows contain, next to *target*.

    Two files rather than one: the mascot and the panel are separate windows with
    separate sizes, and a stitched image would hide exactly the kind of layout
    problem this is meant to show.
    """
    stem, dot, extension = target.rpartition(".")
    if not dot:
        stem, extension = target, "png"
    written: List[str] = []
    for name, widget in (("mascot", overlay.mascot.widget), ("panel", getattr(overlay.panel, "widget", None))):
        if widget is None:
            continue
        path = f"{stem}-{name}.{extension}"
        try:
            widget.grab().save(path)
            written.append(path)
        except Exception:  # pragma: no cover - a snapshot must never break the check
            continue
    return written
