"""A global hotkey, implemented without adding a hard dependency.

``pynput`` gives a portable global listener when it is installed.  When it is not,
the hotkey is quietly skipped (the panel's Listen button and clicking the mascot
both remain) instead of making the app fail to start — which is the whole point of
the lazy-import rule this project follows.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from .. import lazy
from ..control.keys import parse_hotkey

logger = logging.getLogger("naveed.hotkeys")

__all__ = ["HotkeyManager"]


class HotkeyManager:
    """Registers one global chord and calls *callback* when it fires."""

    def __init__(self, hotkey: str, callback: Callable[[], None]) -> None:
        self.hotkey = hotkey
        self.callback = callback
        self.keys: List[str] = list(parse_hotkey(hotkey))
        self._listener: Optional[object] = None
        self._pressed: set = set()

    @property
    def available(self) -> bool:
        return lazy.find_spec_safe("pynput") is not None and bool(self.keys)

    def start(self) -> bool:
        """Begin listening. Returns False when it cannot (never raises)."""
        if not self.available:
            logger.info("global hotkey %s skipped: pynput is not installed", self.hotkey)
            return False
        keyboard = lazy.load("pynput.keyboard", extra="input")
        wanted = {_normalise(key) for key in self.keys}
        manager = self

        def on_press(key) -> None:
            name = _name_of(key)
            if not name:
                return
            manager._pressed.add(name)
            if wanted and wanted <= manager._pressed:
                manager._pressed.clear()
                try:
                    manager.callback()
                except Exception:
                    logger.debug("hotkey callback failed", exc_info=True)

        def on_release(key) -> None:
            name = _name_of(key)
            manager._pressed.discard(name)

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
        self._listener = listener
        logger.info("global hotkey active: %s", self.hotkey)
        return True

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.stop()  # type: ignore[attr-defined]
            except Exception:
                pass


def _normalise(key: str) -> str:
    """Map a key name to the token pynput reports."""
    lowered = key.lower()
    return {
        "control": "ctrl",
        "ctrl": "ctrl",
        "meta": "cmd",
        "alt": "alt",
        "shift": "shift",
        "space": "space",
    }.get(lowered, lowered)


def _name_of(key) -> str:
    """Extract a comparable name from a pynput key event."""
    name = getattr(key, "name", None)
    if name:
        return str(name).lower()
    char = getattr(key, "char", None)
    if char:
        return str(char).lower()
    text = str(key)
    return text.split(".")[-1].lower() if "." in text else text.lower()
