"""The action vocabulary: what Naveed is allowed to *do* on your screen.

One :class:`Action` type is shared by the LLM planner (which emits JSON), the
safety guard (which inspects it), the executor (which performs it) and the panel
(which shows it as a sentence).  Shapes accepted by :func:`normalize_action`:

* brah / OpenAI computer-use style — ``{"type": "click", "x": 10, "y": 20}``,
  ``{"type": "type", "text": "hello"}``, ``{"type": "key", "key": "ctrl+s"}``;
* Naveed's richer style — ``{"action": "open_app", "app": "Notepad"}``;
* a plain string — ``"screenshot"``, ``"scroll down"``.

Coordinates emitted by the model are always **frame-local** (pixels in the
screenshot it was shown).  They are converted to global screen coordinates by
:mod:`naveed.control.os_control` using the monitor the frame came from, which is
the piece naive agents get wrong on multi-monitor and HiDPI setups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .keys import canonical_hotkey, normalize_key, normalize_modifiers

__all__ = [
    "ACTION_KINDS",
    "Action",
    "ActionPlan",
    "describe_actions",
    "normalize_action",
    "normalize_plan",
    "ActionError",
]

#: Every action the executor understands.
ACTION_KINDS: Tuple[str, ...] = (
    "click", "double_click", "right_click", "middle_click", "move", "drag", "scroll",
    "type", "key", "hotkey", "wait", "screenshot", "look",
    "open_app", "open_url", "open_file", "focus_window",
    "shell", "clipboard_get", "clipboard_set", "done", "ask",
    # --- editing, as opposed to clicking and typing -----------------------
    # "read the field, change it, write it back, check it landed" is a different
    # job from "type these characters here", and it is the one users mean when
    # they ask Naveed to edit something anywhere.
    "read_field", "edit_field", "select_all", "find", "undo", "save", "paste",
    # --- knowledge packs and learned routines -----------------------------
    "recipe", "skill_tool",
)

_ALIASES: Dict[str, str] = {
    "left_click": "click",
    "single_click": "click",
    "dblclick": "double_click",
    "doubleclick": "double_click",
    "rightclick": "right_click",
    "middleclick": "middle_click",
    "mouse_move": "move",
    "movemouse": "move",
    "typing": "type",
    "text": "type",
    "type_text": "type",
    "write": "type",
    "keypress": "key",
    "press_key": "key",
    "press": "key",
    "keys": "hotkey",
    "combo": "hotkey",
    "sleep": "wait",
    "pause": "wait",
    "capture": "screenshot",
    "screen": "screenshot",
    "look_at_screen": "look",
    "analyze_screen": "look",
    "launch": "open_app",
    "start_app": "open_app",
    "open_application": "open_app",
    "browse": "open_url",
    "open_link": "open_url",
    "goto": "open_url",
    "navigate": "open_url",
    "switch_window": "focus_window",
    "activate_window": "focus_window",
    "terminal": "shell",
    "run": "shell",
    "command": "shell",
    "finish": "done",
    "complete": "done",
    "answer": "ask",
    # editing
    "get_field": "read_field",
    "field_value": "read_field",
    "read_text": "read_field",
    "set_field": "edit_field",
    "fill_field": "edit_field",
    "update_field": "edit_field",
    "modify_field": "edit_field",
    "change_field": "edit_field",
    "replace_text": "edit_field",
    "append_text": "edit_field",
    "find_replace": "edit_field",
    "search": "find",
    "search_in_page": "find",
    "revert": "undo",
    "save_file": "save",
    "commit": "save",
    "paste_clipboard": "paste",
    # knowledge packs
    "run_recipe": "recipe",
    "playbook": "recipe",
    "macro": "recipe",
    "tool": "skill_tool",
    "api": "skill_tool",
}


class ActionError(ValueError):
    """The model produced something the executor cannot perform."""


@dataclass
class Action:
    """One concrete step."""

    kind: str
    params: Dict[str, Any] = field(default_factory=dict)
    note: str = ""
    #: Frame-local coordinates as produced by the model, when applicable.
    local: bool = True

    # --- accessors ----------------------------------------------------
    def get(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)

    @property
    def x(self) -> Optional[float]:
        value = self.params.get("x")
        return None if value is None else float(value)

    @property
    def y(self) -> Optional[float]:
        value = self.params.get("y")
        return None if value is None else float(value)

    @property
    def text(self) -> str:
        return str(self.params.get("text") or self.params.get("value") or "")

    @property
    def key(self) -> str:
        return str(self.params.get("key") or "")

    @property
    def keys(self) -> Sequence[str]:
        raw = self.params.get("keys") or self.params.get("modifiers") or ()
        if isinstance(raw, str):
            raw = [part for part in raw.replace(" ", "").split("+") if part]
        return tuple(raw)

    @property
    def chord(self) -> str:
        """Canonical chord for key/hotkey actions (``"Control+s"``).

        A ``key`` action with modifiers and a ``hotkey`` action describe the same
        physical event; the executor, the safety guard and the panel's action log
        all want one spelling of it.
        """
        if self.kind == "hotkey":
            return str(self.params.get("hotkey") or "")
        if self.kind == "key":
            parts = [*map(str, self.keys), self.key]
            return "+".join(part for part in parts if part)
        return ""

    @property
    def needs_pointer(self) -> bool:
        return self.kind in ("click", "double_click", "right_click", "middle_click", "move", "drag", "scroll", "edit_field", "read_field")

    @property
    def is_edit(self) -> bool:
        """True for the read-modify-write family, which verifies itself."""
        return self.kind in ("edit_field", "read_field")

    @property
    def writes_text(self) -> bool:
        """True when the action puts text into the machine (guarded for secrets)."""
        return self.kind in ("type", "clipboard_set", "edit_field", "skill_tool")

    @property
    def needs_keyboard(self) -> bool:
        return self.kind in ("type", "key", "hotkey")

    # --- serialisation -------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        payload = {"type": self.kind}
        payload.update(self.params)
        if self.note:
            payload["note"] = self.note
        return payload

    def describe(self) -> str:
        """One short sentence, used in the panel's action log and in speech."""
        if self.note:
            return self.note
        kind = self.kind
        if kind in ("click", "double_click", "right_click", "middle_click"):
            label = {"click": "Clicking", "double_click": "Double-clicking",
                     "right_click": "Right-clicking", "middle_click": "Middle-clicking"}[kind]
            if self.x is not None and self.y is not None:
                return f"{label} at ({int(self.x)}, {int(self.y)})"
            if self.params.get("target"):
                return f"{label} {self.params['target']}"
            return label + "…"
        if kind == "move":
            return f"Moving the pointer to ({int(self.x or 0)}, {int(self.y or 0)})"
        if kind == "drag":
            return f"Dragging to ({int(self.x or 0)}, {int(self.y or 0)})"
        if kind == "scroll":
            amount = int(self.params.get("amount") or self.params.get("dy") or 0)
            direction = "down" if amount > 0 else "up"
            return f"Scrolling {direction} ({abs(amount)}px)"
        if kind == "type":
            preview = self.text.strip().replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "…"
            return f"Typing {preview!r}"
        if kind == "key":
            chord = "+".join([*(str(k) for k in self.keys), self.key]).strip("+")
            return f"Pressing {chord}"
        if kind == "hotkey":
            return f"Pressing {self.get('hotkey') or '+'.join(self.keys)}"
        if kind == "wait":
            return f"Waiting {self.get('seconds', 1)}s"
        if kind == "screenshot":
            return "Taking a screenshot"
        if kind == "look":
            return "Looking at the screen"
        if kind == "open_app":
            return f"Opening {self.get('app')}"
        if kind == "open_url":
            return f"Opening {self.get('url')}"
        if kind == "open_file":
            return f"Opening {self.get('path')}"
        if kind == "focus_window":
            return f"Switching to {self.get('title')}"
        if kind == "shell":
            return f"Running: {self.get('command')}"
        if kind == "clipboard_get":
            return "Reading the clipboard"
        if kind == "clipboard_set":
            return "Copying to the clipboard"
        if kind == "ask":
            return str(self.params.get("question") or "Asking a question")
        if kind == "done":
            return str(self.params.get("summary") or "Done")
        return kind


@dataclass
class ActionPlan:
    """A short ordered list of actions plus the model's own understanding."""

    actions: List[Action] = field(default_factory=list)
    summary: str = ""
    understanding: str = ""
    done: bool = False
    question: str = ""
    #: set when the *model* could not be reached at all. A dead endpoint is not a
    #: question for the user — nobody can answer "connection refused" — so the
    #: task fails immediately with this message instead of waiting for a reply.
    error: str = ""

    def __len__(self) -> int:
        return len(self.actions)

    def __iter__(self):
        return iter(self.actions)

    def describe(self) -> str:
        if self.summary:
            return self.summary
        return describe_actions(self.actions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "understanding": self.understanding,
            "done": self.done,
            "question": self.question,
            "error": self.error,
            "actions": [action.to_dict() for action in self.actions],
        }


def describe_actions(actions: Sequence[Action], *, limit: int = 3) -> str:
    """Join a few action sentences into one readable line."""
    parts = [action.describe() for action in actions[:limit]]
    if len(actions) > limit:
        parts.append(f"+{len(actions) - limit} more")
    return "; ".join(parts) if parts else "nothing to do"


def normalize_action(raw: Union[str, Dict[str, Any], Action]) -> Action:
    """Coerce one model-produced item into an :class:`Action`."""
    if isinstance(raw, Action):
        return raw
    if isinstance(raw, str):
        return _from_string(raw)
    if not isinstance(raw, dict):
        raise ActionError(f"Unsupported action: {raw!r}")

    kind = str(raw.get("type") or raw.get("action") or raw.get("kind") or "").strip().lower()
    if not kind:
        # Some models answer with a single-key object, e.g. {"click": "Save"}.
        for candidate in ACTION_KINDS:
            if candidate in raw:
                kind = candidate
                raw = {"type": candidate, "target": raw[candidate]}
                break
    if not kind:
        raise ActionError(f"Action without a type: {raw!r}")
    kind = _ALIASES.get(kind, kind)
    if kind not in ACTION_KINDS:
        raise ActionError(f"Unknown action type: {kind!r}")

    params: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in ("type", "action", "kind", "note", "reason"):
            continue
        params[key] = value

    # Coordinate aliases models mix up constantly.
    for axis in ("x", "y"):
        if axis not in params:
            for alias in (f"{axis}_coord", f"{axis}coord", f"coord_{axis}"):
                if alias in params:
                    params[axis] = params.pop(alias)
    if "coordinate" in params and "x" not in params and isinstance(params["coordinate"], (list, tuple)) and len(params["coordinate"]) >= 2:
        params["x"], params["y"] = params["coordinate"][0], params["coordinate"][1]
    if "position" in params and "x" not in params and isinstance(params["position"], (list, tuple, dict)):
        position = params.pop("position")
        if isinstance(position, dict):
            params.setdefault("x", position.get("x"))
            params.setdefault("y", position.get("y"))
        else:
            params.setdefault("x", position[0])
            params.setdefault("y", position[1])

    if kind in ("click", "double_click", "right_click", "middle_click", "move", "drag") and params.get("x") is None:
        # "click the Save button" with no coordinates: keep the target text so the
        # executor can look it up through OCR before giving up.
        if params.get("target") or params.get("element") or params.get("text"):
            params.setdefault("target", params.get("element") or params.get("text"))
        else:
            raise ActionError(f"{kind} needs coordinates or a target description: {raw!r}")

    for axis in ("x", "y"):
        if params.get(axis) is not None:
            try:
                params[axis] = float(params[axis])
            except (TypeError, ValueError):
                params.pop(axis, None)

    if kind in ("type",) and not params.get("text") and params.get("value"):
        params["text"] = params["value"]
    if kind == "type" and not str(params.get("text") or "").strip():
        raise ActionError("type needs non-empty text")
    if kind == "key" and not params.get("key") and params.get("keys"):
        keys = params["keys"]
        params["key"] = keys[-1] if isinstance(keys, (list, tuple)) else str(keys)
        if isinstance(keys, (list, tuple)) and len(keys) > 1:
            params["modifiers"] = list(keys[:-1])
            kind = "hotkey"
            params["hotkey"] = "+".join(str(part) for part in keys)
    if kind == "key":
        params["key"] = normalize_key(str(params["key"]))
        params["modifiers"] = list(normalize_modifiers(params.get("modifiers")))
    if kind == "hotkey" and not params.get("hotkey"):
        # Models express chords three different ways: a "hotkey" string, a list
        # under "keys"/"modifiers", or a "key" plus "modifiers". Normalise all of
        # them to one canonical "ctrl+shift+t" string.
        chord_values = params.get("keys") or params.get("modifiers") or ()
        if isinstance(chord_values, str):
            chord_values = [part for part in chord_values.replace(" ", "").split("+") if part]
        parts = [normalize_key(str(part)) for part in chord_values]
        if params.get("key"):
            parts.append(normalize_key(str(params["key"])))
        params["hotkey"] = "+".join(parts)
    if kind == "hotkey" and params.get("hotkey"):
        params["hotkey"] = canonical_hotkey(str(params["hotkey"]))
    if kind == "scroll":
        if params.get("dy") is None and params.get("amount") is None:
            direction = str(params.get("direction") or "down").lower()
            amount = int(params.get("pixels") or 400)
            params["amount"] = amount if direction in ("down", "up") and direction == "down" else -amount
        elif params.get("amount") is None:
            params["amount"] = params.get("dy")

    note = str(raw.get("note") or raw.get("reason") or "")
    return Action(kind=kind, params=params, note=note)


def _from_string(raw: str) -> Action:
    """Parse ``"screenshot"``, ``"scroll down"``, ``"wait 2"`` style shorthand."""
    text = raw.strip()
    lowered = text.lower()
    if lowered in ACTION_KINDS:
        return Action(kind=lowered)
    alias = _ALIASES.get(lowered)
    if alias:
        return Action(kind=alias)
    for prefix in ("scroll ", "wait ", "open_app ", "open ", "type ", "press ", "run "):
        if lowered.startswith(prefix):
            _, _, rest = text.partition(" ")
            body = rest.strip()
            if prefix.startswith("scroll"):
                return normalize_action({"type": "scroll", "direction": body or "down"})
            if prefix.startswith("wait"):
                return normalize_action({"type": "wait", "seconds": float(body or 1)})
            if prefix.startswith("type"):
                return normalize_action({"type": "type", "text": body})
            if prefix.startswith("press"):
                return normalize_action({"type": "key", "key": body})
            if prefix.startswith("run"):
                return normalize_action({"type": "shell", "command": body})
            if body.startswith(("http://", "https://", "www.")):
                return normalize_action({"type": "open_url", "url": body})
            return normalize_action({"type": "open_app", "app": body})
    raise ActionError(f"Could not understand action: {raw!r}")


def normalize_plan(payload: Any, *, limit: int = 12) -> ActionPlan:
    """Build an :class:`ActionPlan` from whatever the model returned.

    Accepts ``{"actions": [...]}``, a bare list, or a single action object, and
    tolerates the many spellings models use for the summary/done fields.
    """
    if isinstance(payload, ActionPlan):
        return payload
    if isinstance(payload, (str, Action)):
        try:
            return ActionPlan(actions=[normalize_action(payload)])
        except ActionError:
            return ActionPlan(summary=str(payload), done=True)

    if isinstance(payload, list):
        plan = ActionPlan(actions=[])
    elif isinstance(payload, dict):
        plan = ActionPlan(
            summary=str(payload.get("summary") or payload.get("message") or ""),
            understanding=str(payload.get("understanding") or payload.get("observation") or payload.get("thought") or ""),
            done=bool(payload.get("done") or payload.get("finished") or payload.get("complete")),
            question=str(payload.get("question") or ""),
        )
        if not plan.actions:
            raw_actions = payload.get("actions") or payload.get("steps") or payload.get("plan")
            if raw_actions is None and payload.get("type"):
                raw_actions = [payload]
            plan.actions = list(raw_actions or [])
    else:
        raise ActionError(f"Unsupported plan payload: {payload!r}")

    actions: List[Action] = []
    errors: List[str] = []
    for entry in plan.actions:
        try:
            actions.append(normalize_action(entry))
        except ActionError as error:
            errors.append(str(error))
        if len(actions) >= limit:
            break
    plan.actions = actions
    if plan.question and not plan.actions:
        plan.actions = [Action(kind="ask", params={"question": plan.question})]
    if errors:
        plan.understanding = (plan.understanding + " | " + "; ".join(errors)).strip(" |")
    return plan
