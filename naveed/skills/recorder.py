"""Teach Naveed a task by performing it once.

This is the honest answer to "train it on our Polarion tasks". Fine-tuning a model
is not something a desktop app can do on your machine — but a new colleague does
not need fine-tuning either. You show them how you do it *once*, and they can do
it again. That is what this module implements:

```
python -m naveed --teach polarion-set-status
   (you do the task normally: click the field, type the value, save)
   Ctrl+Alt+T when you are done
python -m naveed --run-recipe polarion-set-status --arg status=Verified
```

What is recorded, and why it is usable afterwards:

* **click** events with the screen point *and* the offset from the active window's
  top-left — so the recipe survives the window being moved;
* the window title/rectangle in force at each step, so replay can check it is in
  the right app before clicking anything;
* **typed runs**, joined from keystrokes (a run stops at a pause, a click, or a
  chord), plus chords and named keys as chords / key presses;
* a screenshot per click, used at *distillation* time to OCR a label near the
  click point. That label becomes the step's ``anchor``: if the window has moved
  or the layout shifted, the step is relocated by its visible text instead of
  trusting a stale coordinate.

Then distillation turns the event stream into
:class:`naveed.skills.base.Recipe` steps, and the values you typed can be turned
into parameters (``{{status}}``) so the same recipe works for the next work item.
Automatic suggestions are only *suggestions*: names are confirmed with you, or
given explicitly with ``--var "Verified=status"``.

The recorder itself is transport-agnostic — it takes events from anything
(:meth:`ActionRecorder.feed`), which is why the whole pipeline is tested without a
mouse, a keyboard hook, an OCR engine or a display.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .base import Recipe, RecipeStep

logger = logging.getLogger(__name__)

__all__ = [
    "RecordedEvent",
    "ActionRecorder",
    "TeachingSession",
    "distill_recipe",
    "suggest_parameters",
    "Tailer",
]

#: A typed run starts after either a pause, a click, or a chord.
TYPING_GAP_SECONDS = 1.2
#: Two clicks this close together, at (nearly) the same point, are a double click.
DOUBLE_CLICK_SECONDS = 0.45
DOUBLE_CLICK_SLOP = 6
#: Screenshots are taken at most this often while recording.
SCREENSHOT_THROTTLE = 1.0

#: Keys that are meaningful on their own (they become a `key` action).
NAMED_KEYS = {
    "enter", "return", "tab", "escape", "esc", "backspace", "delete", "space",
    "up", "down", "left", "right", "home", "end", "page_up", "page_down", "f5",
    "f2", "insert", "caps_lock",
}

#: What a typed value probably is, so the parameter suggestion is sensible.
_PARAMETER_PATTERNS: Sequence[Tuple[str, str]] = (
    (r"^[A-Z][A-Z0-9]{1,9}-\d{1,6}$", "work_item_id"),
    (r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", "email"),
    (r"^\d{4}-\d{2}-\d{2}$", "date"),
    (r"^https?://", "url"),
)


@dataclass
class RecordedEvent:
    """One thing the user did, in the form the distiller needs."""

    kind: str                       # "click" | "key" | "text"
    at: float = 0.0
    x: int = 0
    y: int = 0
    button: str = "left"
    key: str = ""
    text: str = ""
    modifiers: Tuple[str, ...] = ()
    window: str = ""
    window_rect: Optional[Tuple[int, int, int, int]] = None
    screenshot: str = ""

    def offset(self) -> Optional[Tuple[int, int]]:
        if self.window_rect is None:
            return None
        left, top, _width, _height = self.window_rect
        return (int(self.x - left), int(self.y - top))


@dataclass
class TeachingSession:
    """A recording in progress, and what came of it."""

    name: str
    started: float = field(default_factory=time.time)
    stopped: float = 0.0
    events: List[RecordedEvent] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    window_at_start: str = ""
    window_rect: Optional[Tuple[int, int, int, int]] = None
    recipe: Optional[Recipe] = None

    @property
    def duration(self) -> float:
        return (self.stopped or time.time()) - self.started

    def summary(self) -> str:
        clicks = sum(1 for event in self.events if event.kind == "click")
        keys = sum(1 for event in self.events if event.kind in ("key", "text"))
        return (
            f"{self.name}: {clicks} clicks and {keys} key events in {self.duration:.0f}s "
            f"in {self.window_at_start or 'an unknown window'}"
        )


class ActionRecorder:
    """Collects events from any source and turns them into a recipe."""

    def __init__(
        self,
        name: str,
        *,
        window: Optional[Callable[[], Any]] = None,
        screenshot: Optional[Callable[[], Optional[str]]] = None,
        ocr: Optional[Callable[[str, int, int], str]] = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.session = TeachingSession(name=name)
        self._window = window
        self._screenshot = screenshot
        self._ocr = ocr
        self._now = now
        self._last_screenshot_at = -999.0
        self.recording = False

    # --- lifecycle ------------------------------------------------------
    def start(self) -> TeachingSession:
        self.recording = True
        self.session.started = self._now()
        context = self._window_context()
        self.session.window_at_start = context[0]
        self.session.window_rect = context[1]
        return self.session

    def stop(self) -> TeachingSession:
        self.recording = False
        self.session.stopped = self._now()
        return self.session

    def _window_context(self) -> Tuple[str, Optional[Tuple[int, int, int, int]]]:
        if self._window is None:
            return "", None
        try:
            window = self._window()
        except Exception:
            return "", None
        if window is None:
            return "", None
        title = ""
        for attribute in ("title", "name", "describe"):
            value = getattr(window, attribute, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = None
            if value:
                title = str(value)
                break
        rect = None
        for attribute in ("rect", "bounds", "geometry"):
            value = getattr(window, attribute, None)
            if isinstance(value, (list, tuple)) and len(value) == 4:
                rect = tuple(int(part) for part in value)  # type: ignore[assignment]
                break
        return title, rect

    def _maybe_screenshot(self, event: RecordedEvent) -> None:
        if self._screenshot is None:
            return
        if event.at - self._last_screenshot_at < SCREENSHOT_THROTTLE:
            return
        self._last_screenshot_at = event.at
        try:
            path = self._screenshot()
        except Exception:
            path = None
        if path:
            event.screenshot = str(path)

    # --- events ---------------------------------------------------------
    def feed(self, event: RecordedEvent) -> RecordedEvent:
        """Record one event (the tailer, or a test, calls this)."""
        if not self.recording:
            return event
        if not event.at:
            event.at = self._now()
        title, rect = self._window_context()
        if not event.window:
            event.window = title or self.session.window_at_start
        if event.window_rect is None:
            event.window_rect = rect or self.session.window_rect
        if event.kind == "click":
            self._maybe_screenshot(event)
        self.session.events.append(event)
        return event

    def click(self, x: int, y: int, *, button: str = "left", at: Optional[float] = None) -> RecordedEvent:
        return self.feed(RecordedEvent(kind="click", x=int(x), y=int(y), button=button, at=at or self._now()))

    def key(self, key: str, *, modifiers: Iterable[str] = (), at: Optional[float] = None) -> RecordedEvent:
        return self.feed(
            RecordedEvent(kind="key", key=key.lower(), modifiers=tuple(modifiers), at=at or self._now())
        )

    def type(self, text: str, *, at: Optional[float] = None) -> RecordedEvent:
        return self.feed(RecordedEvent(kind="text", text=text, at=at or self._now()))

    # --- results --------------------------------------------------------
    def recipe(
        self,
        *,
        description: str = "",
        variables: Optional[Dict[str, str]] = None,
        defaults: Optional[Dict[str, Any]] = None,
    ) -> Recipe:
        """Distil the recording into a replayable recipe."""
        recipe = distill_recipe(
            self.session,
            description=description or f"recorded on {time.strftime('%Y-%m-%d', time.localtime(self.session.started))}",
            variables=variables or {},
            ocr=self._ocr,
        )
        if defaults:
            recipe.defaults.update(defaults)
        self.session.recipe = recipe
        return recipe


# --- distillation -----------------------------------------------------------

def distill_recipe(
    session: TeachingSession,
    *,
    description: str = "",
    variables: Optional[Dict[str, str]] = None,
    ocr: Optional[Callable[[str, int, int], str]] = None,
) -> Recipe:
    """Turn a recorded session into recipe steps.

    The rules, in order of how much they matter:

    1. **Typed runs become one ``type`` step.** Character-by-character replay is
       slow and fragile; a run is the unit a person thinks in.
    2. **A chord is a chord.** Anything pressed while ctrl/cmd/alt was held is a
       ``hotkey``, never text.
    3. **Clicks carry their window offset and, when OCR is available, the visible
       label they landed on.** That label is what lets replay find the element
       again after the window has moved.
    4. **Double clicks are recognised** (two clicks, same spot, close in time).
    5. **Values become parameters** only when told to: ``variables`` maps the typed
       text to a parameter name, and :func:`suggest_parameters` offers names.
    """
    variables = {key: value for key, value in (variables or {}).items() if key}
    steps: List[RecipeStep] = []
    events = sorted(session.events, key=lambda event: event.at)

    typed: List[str] = []
    typed_started = 0.0
    typed_modifiers: Tuple[str, ...] = ()
    last_click: Optional[RecordedEvent] = None

    def flush_typing() -> None:
        nonlocal typed
        if not typed:
            return
        text = "".join(typed)
        replacement = variables.get(text)
        steps.append(
            RecipeStep(
                kind="type",
                params={"text": f"{{{{{replacement}}}}}" if replacement else text},
                note=f"typed {len(text)} characters",
                delay=0.25,
            )
        )
        typed = []

    for event in events:
        if event.kind == "text":
            if typed and (event.at - typed_started > TYPING_GAP_SECONDS or typed_modifiers):
                flush_typing()
            if not typed:
                typed_started = event.at
                typed_modifiers = tuple(event.modifiers)
            typed.append(event.text)
            continue

        if event.kind == "key":
            key = (event.key or "").lower()
            modifiers = tuple(modifier.lower() for modifier in event.modifiers)
            if key in NAMED_KEYS and not modifiers:
                if key == "space":
                    # A space during typing belongs to the run, not to a key step.
                    if typed and event.at - typed_started <= TYPING_GAP_SECONDS:
                        typed.append(" ")
                        continue
                flush_typing()
                steps.append(RecipeStep(kind="key", params={"key": key}, note=f"pressed {key}", delay=0.2))
                continue
            if modifiers:
                flush_typing()
                chord = "+".join([*modifiers, key])
                steps.append(RecipeStep(kind="hotkey", params={"hotkey": chord}, note=f"pressed {chord}", delay=0.25))
                continue
            # An unmodified printable character arrives as a key event for some
            # backends; treat it as typing rather than inventing a key name.
            if len(key) == 1:
                if typed and event.at - typed_started > TYPING_GAP_SECONDS:
                    flush_typing()
                if not typed:
                    typed_started = event.at
                typed.append(key)
            continue

        if event.kind == "click":
            flush_typing()
            button = (event.button or "left").lower()
            offset = event.offset()
            is_double = (
                last_click is not None
                and button == last_click.button
                and event.at - last_click.at <= DOUBLE_CLICK_SECONDS
                and abs(event.x - last_click.x) <= DOUBLE_CLICK_SLOP
                and abs(event.y - last_click.y) <= DOUBLE_CLICK_SLOP
            )
            if is_double:
                # Replace the single click we already emitted with a double click.
                if steps and steps[-1].kind == "click":
                    steps.pop()
                kind = "double_click"
            else:
                kind = {"right": "right_click", "middle": "middle_click"}.get(button, "click")

            params: Dict[str, Any] = {}
            anchor = ""
            if ocr is not None and event.screenshot:
                try:
                    anchor = (ocr(event.screenshot, event.x, event.y) or "").strip()
                except Exception:
                    anchor = ""
            params["x"] = event.x
            params["y"] = event.y
            if anchor:
                params["target"] = anchor
            steps.append(
                RecipeStep(
                    kind=kind,
                    params=params,
                    note=("clicked " + anchor) if anchor else "clicked",
                    anchor=anchor,
                    window=event.window or session.window_at_start,
                    offset=offset,
                    button=button,
                    delay=0.4,
                )
            )
            last_click = event
            continue

    flush_typing()

    recipe = Recipe(
        name=session.name,
        description=description,
        app=session.window_at_start,
        params={name: "recorded value" for name in sorted(set(variables.values()))},
        steps=steps,
        skill="",
        learned=True,
    )
    return recipe


def suggest_parameters(values: Sequence[str]) -> Dict[str, str]:
    """Guess which recorded values should become parameters.

    Returns ``{recorded text: suggested parameter name}``. Deliberately shy: a
    short value is left alone (it is probably a fixed label like "Verified"),
    while a work-item ID, an email, a date or a URL is almost certainly the part
    that changes per run.
    """
    suggestions: Dict[str, str] = {}
    used: Dict[str, int] = {}
    for value in values:
        text = (value or "").strip()
        if len(text) < 3:
            continue
        name = ""
        for pattern, candidate in _PARAMETER_PATTERNS:
            if re.match(pattern, text):
                name = candidate
                break
        if not name and len(text) >= 12:
            name = "text"
        if not name:
            continue
        # Keep names unique when several values suggest the same one.
        count = used.get(name, 0)
        used[name] = count + 1
        if count:
            name = f"{name}_{count + 1}"
        suggestions[text] = name
    return suggestions


# --- the live tailer --------------------------------------------------------

class Tailer:
    """Wires real mouse/keyboard hooks into an :class:`ActionRecorder`.

    This is the only part that needs a display and `pynput`, which is why it is
    kept away from the distillation logic: everything above can be tested, and
    this thin adapter can be exercised on a real desktop.
    """

    def __init__(self, recorder: ActionRecorder) -> None:
        self.recorder = recorder
        self.mouse = None
        self.keyboard = None
        self._modifiers: set = set()
        self._last_click_at = 0.0
        self._last_click_point: Tuple[int, int] = (0, 0)

    def available(self) -> bool:
        try:
            from .. import lazy

            return lazy.find_spec_safe("pynput") is not None
        except Exception:
            return False

    def start(self) -> bool:
        """Begin listening. Returns False (with a reason in the log) if it cannot."""
        from .. import lazy

        try:
            mouse = lazy.load("pynput.mouse", extra="input")
            keyboard = lazy.load("pynput.keyboard", extra="input")
        except Exception as error:
            logger.info("recording needs pynput: %s", error)
            return False

        def on_click(x, y, button, pressed):
            if not pressed:
                return
            point = (int(x), int(y))
            now = time.time()
            is_double = now - self._last_click_at <= DOUBLE_CLICK_SECONDS and (
                abs(point[0] - self._last_click_point[0]) <= DOUBLE_CLICK_SLOP
                and abs(point[1] - self._last_click_point[1]) <= DOUBLE_CLICK_SLOP
            )
            if is_double:
                # Feed both clicks: the distiller folds them into one double click.
                self.recorder.click(point[0], point[1], button=str(button).split(".")[-1].lower(), at=now)
            self.recorder.click(point[0], point[1], button=str(button).split(".")[-1].lower(), at=now)
            self._last_click_at = now
            self._last_click_point = point

        def on_press(key):
            name = self._key_name(key)
            if name in ("ctrl", "cmd", "alt", "shift", "ctrl_l", "ctrl_r", "cmd_l", "cmd_r", "alt_l", "alt_r", "shift_l", "shift_r"):
                self._modifiers.add(name.replace("_l", "").replace("_r", ""))
                return
            modifiers = tuple(sorted(self._modifiers))
            if not modifiers and len(name) == 1:
                self.recorder.type(name)
            else:
                self.recorder.key(name, modifiers=modifiers)

        def on_release(key):
            name = self._key_name(key).replace("_l", "").replace("_r", "")
            self._modifiers.discard(name)

        try:
            self.mouse = mouse.Listener(on_click=on_click)
            self.keyboard = keyboard.Listener(on_press=on_press, on_release=on_release)
            self.mouse.start()
            self.keyboard.start()
            return True
        except Exception as error:
            logger.info("could not start the input listeners: %s", error)
            return False

    def stop(self) -> None:
        for listener in (self.mouse, self.keyboard):
            try:
                if listener is not None:
                    listener.stop()
            except Exception:
                pass
        self.mouse = None
        self.keyboard = None

    @staticmethod
    def _key_name(key: Any) -> str:
        char = getattr(key, "char", None)
        if char:
            return char
        name = getattr(key, "name", None)
        if name:
            return str(name)
        return str(key).replace("Key.", "").lower()
