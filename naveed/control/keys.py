"""Key-name normalisation shared by every input backend.

Ported from **brah** (https://github.com/KenKaiii/brah, MIT) —
``src/realtime/tools/computer-use-actions.js`` — which defines a small alias
table so a model can say ``ENTER``, ``return``, ``ESC`` or ``cmd+s`` and the
input layer still presses the right physical key.

Naveed adds :func:`parse_hotkey` (for ``"ctrl+alt+space"`` style config strings)
and :func:`key_for_platform` (``Meta`` on macOS, ``Win`` on Windows), because a
small model writing "cmd+s" on Windows should still work.
"""

from __future__ import annotations

import sys
from typing import Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "KEY_ALIASES",
    "canonical_hotkey",
    "MODIFIER_KEYS",
    "normalize_drag_path",
    "normalize_key",
    "normalize_modifiers",
    "parse_hotkey",
    "key_for_platform",
]

#: Byte-for-byte the alias table from brah, with a few additions for shortcuts.
KEY_ALIASES = {
    "ENTER": "Enter",
    "RETURN": "Enter",
    "ESC": "Escape",
    "ESCAPE": "Escape",
    "CTRL": "Control",
    "CONTROL": "Control",
    "CMD": "Meta",
    "COMMAND": "Meta",
    "META": "Meta",
    "SUPER": "Meta",
    "WIN": "Meta",
    "WINDOWS": "Meta",
    "OPTION": "Alt",
    "ALT": "Alt",
    "SHIFT": "Shift",
    "TAB": "Tab",
    "SPACE": "Space",
    "SPACEBAR": "Space",
    "BACKSPACE": "Backspace",
    "DELETE": "Delete",
    "DEL": "Delete",
    "INSERT": "Insert",
    "HOME": "Home",
    "END": "End",
    "PAGEUP": "PageUp",
    "PGUP": "PageUp",
    "PAGEDOWN": "PageDown",
    "PGDN": "PageDown",
    "ARROWUP": "ArrowUp",
    "UP": "ArrowUp",
    "ARROWDOWN": "ArrowDown",
    "DOWN": "ArrowDown",
    "ARROWLEFT": "ArrowLeft",
    "LEFT": "ArrowLeft",
    "ARROWRIGHT": "ArrowRight",
    "RIGHT": "ArrowRight",
    "CAPSLOCK": "CapsLock",
    "PRINTSCREEN": "PrintScreen",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4", "F5": "F5", "F6": "F6",
    "F7": "F7", "F8": "F8", "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
    "PLUS": "+",
    "MINUS": "-",
    "EQUALS": "=",
    "COMMA": ",",
    "PERIOD": ".",
    "SLASH": "/",
    "BACKSLASH": "\\",
    "SEMICOLON": ";",
    "QUOTE": "'",
    "GRAVE": "`",
}

MODIFIER_KEYS = frozenset({"Alt", "Control", "Meta", "Shift"})


def normalize_key(key: str, *, platform: Optional[str] = None) -> str:
    """Turn any spelling of a key into the canonical name.

    Unknown keys are returned stripped, not rejected: a model that invents
    ``"F13"`` or a letter should not break the whole task.
    """
    if not isinstance(key, str):
        raise TypeError("Computer key must be a string.")
    trimmed = key.strip()
    if not trimmed:
        raise ValueError("Computer key must not be empty.")
    if len(trimmed) == 1:
        return trimmed
    compact = trimmed.replace(" ", "").replace("_", "").replace("-", "").upper()
    resolved = KEY_ALIASES.get(compact, trimmed)
    return key_for_platform(resolved, platform=platform)


def key_for_platform(key: str, *, platform: Optional[str] = None) -> str:
    """Map the *conceptual* Meta key to the platform's own name.

    ``"cmd+s"`` from a model that assumes macOS becomes ``"Meta+s"`` on macOS
    (unchanged) and is left alone elsewhere — the backends themselves translate
    ``Meta`` to the Windows/Super key.
    """
    platform = platform or sys.platform
    if key == "Command":
        return "Meta"
    if platform.startswith("darwin"):
        return key
    if key in ("Meta", "Win", "Super"):
        return "Meta"
    return key


def normalize_modifiers(keys: Optional[Iterable[str]], *, platform: Optional[str] = None) -> Tuple[str, ...]:
    """Keep only real modifier keys, canonicalised and de-duplicated."""
    if not keys:
        return ()
    result: List[str] = []
    for raw in keys:
        try:
            resolved = normalize_key(raw, platform=platform)
        except (TypeError, ValueError):
            continue
        if resolved in MODIFIER_KEYS and resolved not in result:
            result.append(resolved)
    return tuple(result)


def parse_hotkey(hotkey: str, *, platform: Optional[str] = None) -> Tuple[str, ...]:
    """Parse ``"ctrl+alt+space"`` into canonical keys.

    Accepts ``+``, ``-`` or surrounding whitespace as separators; a literal
    ``+`` key can be written as ``"plus"``.
    """
    if not hotkey or not hotkey.strip():
        return ()
    text = hotkey.strip()
    separators = "+"
    if "-" in text and "+" not in text:
        separators = "-"
    parts = [part for part in text.replace(" ", "").split(separators) if part]
    resolved: List[str] = []
    for part in parts:
        try:
            resolved.append(normalize_key(part, platform=platform))
        except (TypeError, ValueError):
            continue
    return tuple(resolved)


def canonical_hotkey(hotkey: str, *, platform: Optional[str] = None) -> str:
    """Canonicalise any chord spelling to ``"Control+Shift+T"`` form.

    Used so that ``"ctrl+s"``, ``"Ctrl-S"`` and ``["ctrl", "s"]`` all become the
    same string before it is stored in an action, compared, or displayed.
    """
    parts = parse_hotkey(hotkey, platform=platform) if isinstance(hotkey, str) else tuple(hotkey or ())
    return "+".join(parts)


def normalize_drag_path(path: Sequence) -> List[Tuple[int, int]]:
    """Port of brah's ``normalizeDragPath``: ``[[x, y], ...]`` -> ``[(x, y), ...]``."""
    if not path or len(path) < 2:
        raise ValueError("Drag path must contain at least two points.")
    points: List[Tuple[int, int]] = []
    for entry in path:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            points.append((int(entry[0]), int(entry[1])))
        elif isinstance(entry, dict) and "x" in entry and "y" in entry:
            points.append((int(entry["x"]), int(entry["y"])))
        else:
            raise ValueError(f"Unsupported drag point: {entry!r}")
    return points
