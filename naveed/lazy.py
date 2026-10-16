"""Lazy import helpers.

Naveed is a *floating desktop companion*: the moment the app starts, the mascot
has to be on screen and animated.  Every heavy third-party dependency in this
project is therefore imported only at the instant the feature that needs it is
actually used, never at start-up.

Design rules used across the codebase
-------------------------------------
1. ``import`` statements at module top level are limited to the standard
   library and to other ``naveed`` modules that are themselves cheap.
2. Heavy modules (PySide6, mss, PIL, numpy, sounddevice, faster-whisper, piper,
   pynput, pyautogui, win32 ctypes tables, ...) are pulled in through
   :func:`load`, :func:`optional` or :func:`lazy_module` **inside the function
   that needs them**, so a machine that only runs the screen watcher never pays
   for the Qt import and a machine without a microphone never pays for the
   speech stack.
3. Missing dependencies raise :class:`MissingDependencyError`, which names the
   feature, the extra and the exact ``pip install`` line.  A bare
   ``ModuleNotFoundError`` from deep inside a call stack is considered a bug.
4. ``python -m naveed --check`` prints :func:`report`, the live map of which
   lazy dependency is installed and which feature it unlocks.
"""

from __future__ import annotations

import importlib
import importlib.util
import threading
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

__all__ = [
    "MissingDependencyError",
    "available",
    "clear_cache",
    "find_spec_safe",
    "install_hint",
    "lazy_attrs",
    "lazy_module",
    "load",
    "missing",
    "optional",
    "report",
    "requires",
]

# --- dependency metadata -----------------------------------------------------

#: module name -> (pip name, extra, what it unlocks in Naveed)
DEPENDENCIES: Dict[str, tuple] = {
    "PySide6": ("PySide6", "ui", "the floating mascot, the glass control panel and the tray"),
    "PySide6.QtWidgets": ("PySide6", "ui", "the floating mascot widgets"),
    "PySide6.QtGui": ("PySide6", "ui", "painting, icons and screen grabbing"),
    "PySide6.QtCore": ("PySide6", "ui", "timers, signals and geometry"),
    "mss": ("mss", "capture", "fast multi-monitor screen capture"),
    "PIL": ("Pillow", "capture", "image decoding, diffing and artifact saving"),
    "numpy": ("numpy", "capture", "fast frame diffing for the screen watcher"),
    "pynput": ("pynput", "input", "keyboard/mouse input and the global hotkey"),
    "pyautogui": ("PyAutoGUI", "input", "fallback mouse/keyboard input backend"),
    "sounddevice": ("sounddevice", "voice", "microphone capture for voice commands"),
    "faster_whisper": ("faster-whisper", "voice", "offline speech-to-text"),
    "vosk": ("vosk", "voice", "lightweight offline speech-to-text and wake word"),
    "piper": ("piper-tts", "voice", "offline neural text-to-speech"),
    "pyttsx3": ("pyttsx3", "voice", "built-in OS text-to-speech fallback"),
    "soundfile": ("soundfile", "voice", "playing synthesised speech"),
    "Quartz": ("pyobjc-framework-Quartz", "mac", "macOS screen capture status and Core Graphics input"),
    "win32gui": ("pywin32", "win", "window titles, geometry and focus on Windows"),
    "win32con": ("pywin32", "win", "window constants on Windows"),
    "win32api": ("pywin32", "win", "process and window helpers on Windows"),
    "httpx": ("httpx", "llm", "async HTTP for the small-LLM planner"),
}


class MissingDependencyError(ImportError):
    """Raised when a lazily imported dependency is not installed.

    The message always explains *which feature* is blocked and *how to install*
    the module, so the user never has to read a stack trace to fix it.
    """

    def __init__(
        self,
        name: str,
        *,
        extra: Optional[str] = None,
        reason: Optional[BaseException] = None,
        detail: Optional[str] = None,
    ) -> None:
        self.name = name
        self.extra = extra
        self.reason = reason
        message = install_hint(name, extra=extra)
        if detail:
            message = f"{message}\n{detail}"
        if reason is not None and not isinstance(reason, ModuleNotFoundError):
            message = f"{message}\nImport error: {reason}"
        super().__init__(message)


# --- internals --------------------------------------------------------------

_lock = threading.RLock()
_cache: Dict[str, Any] = {}


def find_spec_safe(name: str) -> Optional[object]:
    """Return ``importlib`` spec for *name*, or ``None`` when unavailable.

    ``find_spec`` imports parent packages and can raise ``ValueError`` /
    ``ImportError`` for odd environments (frozen apps, namespace packages), so
    every failure is collapsed into ``None``: the caller only wants a yes/no.
    """
    try:
        return importlib.util.find_spec(name)
    except (ImportError, AttributeError, ValueError, ModuleNotFoundError):
        return None


def metadata(name: str) -> tuple:
    """Return ``(pip_name, extra, feature)`` for a module, with sane defaults."""
    pip_name, extra, feature = DEPENDENCIES.get(name, (name, None, "this feature"))
    return pip_name, extra, feature


def install_hint(name: str, *, extra: Optional[str] = None) -> str:
    """Human-readable, copy-pasteable install instructions for *name*."""
    pip_name, default_extra, feature = metadata(name)
    extra = extra if extra is not None else default_extra
    lines = [
        f"{name} is not installed, and Naveed needs it for {feature}.",
        "  Naveed keeps every heavy import lazy, so nothing else is affected.",
        "  Install it with one of:",
    ]
    if extra:
        lines.append(f'    pip install "naveed[{extra}]"')
    lines.append(f"    pip install {pip_name}")
    return "\n".join(lines)


def load(name: str, *, attr: Optional[str] = None, extra: Optional[str] = None) -> Any:
    """Import *name* (optionally ``attr`` from it), caching the result.

    This is the single entry point used by the rest of Naveed, e.g.
    ``QtWidgets = lazy.load("PySide6.QtWidgets")`` inside a paint routine.
    """
    key = f"{name}:{attr}" if attr else name
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
    try:
        module = importlib.import_module(name)
        result = getattr(module, attr) if attr else module
    except ImportError as error:  # pragma: no cover - depends on environment
        raise MissingDependencyError(name, extra=extra, reason=error) from error
    except AttributeError as error:  # pragma: no cover - bad attr request
        raise MissingDependencyError(name, extra=extra, reason=error) from error
    with _lock:
        _cache[key] = result
    return result


def optional(name: str, *, attr: Optional[str] = None) -> Any:
    """Like :func:`load` but returns ``None`` instead of raising."""
    try:
        return load(name, attr=attr)
    except MissingDependencyError:
        return None


def available(*names: str) -> bool:
    """True when every module in *names* can be imported."""
    return all(find_spec_safe(name) is not None for name in names)


def missing(*names: str) -> Sequence[str]:
    """Subset of *names* that is not importable."""
    return tuple(name for name in names if find_spec_safe(name) is None)


def clear_cache() -> None:
    """Drop the import cache (used by tests and by ``--reload``)."""
    with _lock:
        _cache.clear()


class LazyModule(ModuleType):
    """A module-shaped proxy whose real import happens on first attribute use.

    ``widgets = lazy_module("PySide6.QtWidgets")`` keeps module semantics
    (``widgets.QPushButton``, ``from ... import``) while deferring the cost.
    """

    __slots__ = ("_target", "_resolved", "_extra")

    def __init__(self, target: str, *, extra: Optional[str] = None) -> None:
        super().__init__(f"naveed.lazy:{target}")
        self._target = target
        self._resolved: Optional[ModuleType] = None
        self._extra = extra

    def _module(self) -> ModuleType:
        resolved = self._resolved
        if resolved is None:
            resolved = load(self._target, extra=self._extra)
            self._resolved = resolved
        return resolved

    def __getattr__(self, item: str) -> Any:
        if item.startswith("__") and item.endswith("__"):
            # Keep protocol lookups (__path__, __all__, ...) off the import path.
            raise AttributeError(item)
        return getattr(self._module(), item)

    def __dir__(self) -> list:
        return sorted(set(super().__dir__()) | set(dir(self._module())))


def lazy_module(target: str, *, extra: Optional[str] = None) -> LazyModule:
    """Public constructor for :class:`LazyModule`."""
    return LazyModule(target, extra=extra)


def lazy_attrs(
    namespace: Mapping[str, Any],
    mapping: Mapping[str, str],
    *,
    extra: Optional[str] = None,
) -> Callable[[str], Any]:
    """Build a module-level ``__getattr__`` that resolves *mapping* on demand.

    Example (``naveed/overlay/__init__.py``)::

        __getattr__ = lazy_attrs(globals(), {
            "MascotWindow": "naveed.overlay.window:MascotWindow",
            "mascot": "naveed.overlay.mascot",
        })

    Accepted target forms:

    * ``"naveed.overlay.window:MascotWindow"`` — explicit module + attribute
      (**preferred**, unambiguous);
    * ``"naveed.overlay.mascot"`` — a *module*, imported as-is.  A dotted target
      is always tried as a module first, because treating ``pkg.sub`` as
      "attribute ``sub`` of ``pkg``" would call straight back into this same
      ``__getattr__`` and recurse forever;
    * ``"naveed.overlay.window.MascotWindow"`` — module + attribute, only used
      when the whole string is not itself importable.
    """
    del namespace  # kept for symmetry with a module __getattr__ signature
    resolving: set = set()

    def __getattr__(name: str) -> Any:
        target = mapping.get(name)
        if target is None:
            raise AttributeError(f"module has no attribute {name!r}")
        if name in resolving:
            # A self-referential mapping would otherwise recurse until Python
            # gives up; fail loudly instead of looping.
            raise AttributeError(f"lazy attribute {name!r} resolves to itself ({target!r})")
        resolving.add(name)
        try:
            if ":" in target:
                module_name, _, attr = target.partition(":")
                return load(module_name, attr=attr, extra=extra)
            # A real sub-module (checked the cheap way, without importing).
            if find_spec_safe(target) is not None:
                return load(target, extra=extra)
            if "." in target:
                module_name, _, attr = target.rpartition(".")
                return load(module_name, attr=attr, extra=extra)
            return load(target, extra=extra)
        finally:
            resolving.discard(name)

    return __getattr__


def requires(name: str, *, extra: Optional[str] = None, attr: Optional[str] = None) -> Callable:
    """Decorator that resolves a lazy dependency before the call body runs."""

    def decorator(function: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            load(name, attr=attr, extra=extra)
            return function(*args, **kwargs)

        wrapper.__name__ = getattr(function, "__name__", "wrapped")
        wrapper.__doc__ = function.__doc__
        wrapper.__dict__["__lazy_requires__"] = (name, extra, attr)
        return wrapper

    return decorator


def report(names: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Availability map for ``python -m naveed --check``."""
    result: Dict[str, Dict[str, Any]] = {}
    for name in names or DEPENDENCIES:
        pip_name, extra, feature = metadata(name)
        result[name] = {
            "installed": find_spec_safe(name) is not None,
            "pip": pip_name,
            "extra": extra,
            "feature": feature,
        }
    return result
