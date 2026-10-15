"""The rolling world model of the desktop.

Derived from **OpenDesktop** (https://github.com/atum246/OpenDesktop, MIT) —
``src/screen-state/index.js`` ("Screen-as-State Machine"), which keeps a bounded
history of screen states and a graph of transitions so the agent can reason
about *what changed* instead of only *what is*.

Naveed keeps the state record, the element fingerprinting and the transition
graph, and adds:

* the active window (title/process) on every state, so a state is self-describing;
* ``summary`` — one sentence the small LLM planner can read without an image;
* JSON serialisation, so a session can be replayed or attached to a bug report.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


__all__ = ["ScreenState", "ScreenStateGraph", "UIElement", "fingerprint_element", "summarize_state"]

Rect = Tuple[int, int, int, int]


def _new_state_id() -> str:
    """Short, sortable, unique-enough state id (timestamp + random suffix)."""
    from uuid import uuid4

    return f"{int(time.time() * 1000):x}-{uuid4().hex[:6]}"


@dataclass
class UIElement:
    """One interactable thing seen on screen.

    Presently populated from the active-window geometry and from OCR when the
    optional OCR extra is installed; kept as a first-class type because both the
    planner prompt and the click-target resolution read it.
    """

    kind: str = "unknown"  # button, field, menu, link, text, window
    text: str = ""
    bounds: Optional[Rect] = None
    interactable: bool = False
    state: str = ""  # enabled, focused, selected, ...
    confidence: float = 0.0

    def fingerprint(self) -> str:
        return fingerprint_element(self)

    def as_dict(self) -> dict:
        return asdict(self)


def fingerprint_element(element: UIElement) -> str:
    """Stable identity for an element across frames.

    Port of OpenDesktop's ``_fingerprintElement``: identity is kind + text +
    coarsely rounded bounds, so the same button keeps its id when the page
    scrolls by a few pixels.
    """
    kind = (element.kind or "").strip().lower()
    text = " ".join((element.text or "").split()).lower()[:80]
    bounds = element.bounds or (0, 0, 0, 0)
    coarse = tuple(int(value // 8) * 8 for value in bounds)
    payload = f"{kind}|{text}|{coarse}".encode("utf-8", errors="replace")
    return hashlib.blake2b(payload, digest_size=6).hexdigest()


@dataclass
class ScreenState:
    """Everything Naveed knows about the desktop at one instant."""

    id: str = field(default_factory=_new_state_id)
    captured_at: float = field(default_factory=time.time)
    monitor: Optional[Dict[str, Any]] = None
    window: Optional[Dict[str, Any]] = None
    width: int = 0
    height: int = 0
    frame_hash: str = ""
    changed: bool = False
    scene: bool = False
    first_frame: bool = False
    diff_ratio: float = 0.0
    path: str = ""
    by: str = ""
    elements: List[UIElement] = field(default_factory=list)
    text: str = ""
    ocr_status: str = "not_requested"
    summary: str = ""

    # --- convenience -------------------------------------------------
    @property
    def monitor_index(self) -> int:
        return int((self.monitor or {}).get("index", 0))

    @property
    def app(self) -> str:
        window = self.window or {}
        return str(window.get("process") or window.get("title") or "unknown")

    @property
    def title(self) -> str:
        return str((self.window or {}).get("title") or "")

    @property
    def timestamp_iso(self) -> str:
        return datetime.fromtimestamp(self.captured_at, tz=timezone.utc).isoformat(timespec="seconds")

    @property
    def percent(self) -> float:
        return round(self.diff_ratio * 100.0, 2)

    def to_prompt_line(self) -> str:
        """Compact line for an LLM prompt budget."""
        if not self.summary:
            self.summary = summarize_state(self)
        return f"[{self.timestamp_iso}] {self.summary}"

    def as_dict(self) -> dict:
        payload = asdict(self)
        return payload

    def to_json(self, *, indent: Optional[int] = None) -> str:
        return json.dumps(self.as_dict(), indent=indent, default=str)


def summarize_state(state: ScreenState, *, previous: Optional[ScreenState] = None) -> str:
    """One-line, prompt-friendly description of a :class:`ScreenState`."""
    bits: List[str] = []
    app = state.app
    title = state.title
    if title and title.lower() not in app.lower():
        bits.append(f"{app} — {title[:70]}")
    elif app:
        bits.append(app)
    else:
        bits.append("desktop")
    bits.append(f"{state.width}x{state.height} on monitor {state.monitor_index}")
    if state.first_frame:
        bits.append("first frame")
    elif state.scene:
        bits.append(f"screen changed completely ({state.percent}%)")
    elif state.changed:
        bits.append(f"changed {state.percent}%")
    else:
        bits.append("unchanged")
    if state.text:
        bits.append(f"text: {state.text[:120]!r}")
    if state.elements:
        bits.append(f"{len(state.elements)} elements")
    return ", ".join(bits)


class ScreenStateGraph:
    """Bounded history of screen states plus their transitions.

    Both a ring buffer (``recent``) and a transition map (``transitions``) are
    kept: the buffer answers "what has been happening", the map answers "what
    tends to follow this state", which is the part OpenDesktop used for workflow
    replay and which Naveed uses to notice it is stuck in a loop.
    """

    def __init__(self, *, max_history: int = 100, max_transitions: int = 500) -> None:
        self.max_history = max(1, max_history)
        self.max_transitions = max(1, max_transitions)
        self._history: List[ScreenState] = []
        self._transitions: Dict[str, Dict[str, int]] = {}

    # --- recording ---------------------------------------------------
    def record(self, state: ScreenState) -> Optional[Tuple[str, str]]:
        """Append *state*, returning the ``(from_id, to_id)`` transition if any."""
        transition = None
        if self._history:
            previous = self._history[-1]
            key = previous.frame_hash or previous.id
            bucket = self._transitions.setdefault(key, {})
            bucket[state.frame_hash or state.id] = bucket.get(state.frame_hash or state.id, 0) + 1
            if len(self._transitions) > self.max_transitions:
                self._trim_transitions()
            if state.changed:
                transition = (previous.id, state.id)
        self._history.append(state)
        if len(self._history) > self.max_history:
            del self._history[: len(self._history) - self.max_history]
        return transition

    def _trim_transitions(self) -> None:
        for key in list(self._transitions)[: len(self._transitions) - self.max_transitions]:
            self._transitions.pop(key, None)

    # --- reading -----------------------------------------------------
    @property
    def history(self) -> Sequence[ScreenState]:
        return tuple(self._history)

    @property
    def last(self) -> Optional[ScreenState]:
        return self._history[-1] if self._history else None

    def recent(self, count: int = 10) -> List[ScreenState]:
        return self._history[-max(0, count):]

    def changed_states(self, count: int = 5) -> List[ScreenState]:
        return [state for state in self._history if state.changed][-count:]

    def is_oscillating(self, window: int = 6) -> bool:
        """True when the screen is flipping between the same two frames.

        This is the "the agent's click did nothing" signal: capture/act loops
        that keep producing the same pair of hashes should back off instead of
        clicking forever.
        """
        hashes = [state.frame_hash for state in self._history[-window:] if state.frame_hash]
        if len(hashes) < 4:
            return False
        unique = set(hashes)
        if len(unique) > 2:
            return False
        return max(hashes.count(value) for value in unique) >= 3

    def describe(self, count: int = 8) -> str:
        """Multi-line timeline used to brief the planner or debug a run."""
        lines = []
        for state in self.recent(count):
            lines.append(("  * " if state.changed else "    ") + state.to_prompt_line())
        return "\n".join(lines) if lines else "    (no frames captured yet)"

    def clear(self) -> None:
        self._history.clear()
        self._transitions.clear()

    def to_json(self, count: int = 20) -> str:
        return json.dumps([state.as_dict() for state in self.recent(count)], indent=2, default=str)

    def stats(self) -> Dict[str, Any]:
        changed = sum(1 for state in self._history if state.changed)
        scenes = sum(1 for state in self._history if state.scene)
        return {
            "frames": len(self._history),
            "changed": changed,
            "scenes": scenes,
            "transitions": sum(len(bucket) for bucket in self._transitions.values()),
            "oscillating": self.is_oscillating(),
        }
