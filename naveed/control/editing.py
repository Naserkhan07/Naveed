"""Editing text *anywhere*, safely and verifiably.

Clicking and typing blind is what makes computer-use agents feel broken: they
retype a whole field to change one word, they clobber text they never read, and
they cannot tell whether the edit landed. This module implements the thing a
person actually does when editing a field in an unfamiliar web app:

1. **Locate** the field (coordinates, or its visible label via OCR, or whatever
   currently has focus).
2. **Read** its exact current value — click it, select all, copy, and read the
   *clipboard*. Not OCR: OCR mis-reads characters, and an edit written on a
   mis-read field silently corrupts the user's data. The clipboard is exact.
3. **Modify** that text in Python, with no screen involved
   (:func:`apply_edit` — a pure function, so every edit rule is unit-testable).
4. **Write** the result back, by pasting (exact, and fast for long text) with
   typing as the fallback.
5. **Verify** by reading the field again and comparing. One retry, then an honest
   failure — never a silent claim of success.

Two details make step 2 trustworthy rather than hopeful:

* **The sentinel check.** A clipboard read only counts if the clipboard provably
  changed: Naveed writes a unique sentinel, presses Ctrl+A/Ctrl+C, and accepts the
  result only if the sentinel is gone. Without that, a field that ignores Ctrl+C
  hands back the *previous* clipboard and Naveed would happily "read" unrelated
  text and write an edit built on it.
* **Read-back verification of the write.** After pasting, the same procedure runs
  again; the edit is only reported as done when the field agrees.

:class:`FieldEditor` takes the input controller as a duck-typed object, so the
whole flow is tested with a fake controller and a fake field
(``tests/test_editing.py``) — no screen, no Qt, no clipboard.

This is what turns "click and type" into "edit any task, anywhere".
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "EditOperation",
    "EditRequest",
    "EditOutcome",
    "FieldReading",
    "FieldEditor",
    "apply_edit",
    "EDIT_OPERATIONS",
    "parse_edit_request",
]


class EditOperation(str, Enum):
    """What to do with the value that is already in the field."""

    SET = "set"                  # replace everything with `value`
    APPEND = "append"            # add `value` at the end
    PREPEND = "prepend"          # add `value` at the start
    REPLACE = "replace"          # replace every occurrence of `old` with `new`
    REMOVE = "remove"            # delete every occurrence of `old`
    INSERT_AFTER = "insert_after"      # add `value` after `marker`
    INSERT_BEFORE = "insert_before"    # add `value` before `marker`
    CLEAR = "clear"              # empty the field
    TRIM = "trim"                # strip surrounding whitespace
    UPPER = "upper"
    LOWER = "lower"


EDIT_OPERATIONS: Tuple[str, ...] = tuple(operation.value for operation in EditOperation)

#: Words a model may emit instead of the canonical operation name.
_OPERATION_ALIASES: Dict[str, str] = {
    "overwrite": "set",
    "write": "set",
    "fill": "set",
    "replace_all": "set",
    "add": "append",
    "add_to_end": "append",
    "suffix": "append",
    "add_to_start": "prepend",
    "prefix": "prepend",
    "swap": "replace",
    "find_replace": "replace",
    "delete": "remove",
    "delete_text": "remove",
    "insert": "insert_after",
    "strip": "trim",
    "uppercase": "upper",
    "lowercase": "lower",
    "empty": "clear",
}


#: Ways a caller says "the thing I already have the keyboard focus in, do not
#: click anything".  Editing *anywhere* has to include the case where the field
#: cannot be named or seen clearly — a caret in a code editor, a rich-text box
#: inside a dialog, a cell that was already open — and clicking a guessed point
#: there is how you edit the wrong thing.
FOCUSED_WORDS: Tuple[str, ...] = (
    "",
    "focused",
    "focus",
    "current",
    "current field",
    "this",
    "this field",
    "active",
    "active field",
    "selected",
    "selection",
    "cursor",
    "here",
)


def is_focused_target(text: Any) -> bool:
    """True when *text* means "whatever has focus", not a label to look for."""
    if text is None:
        return True
    candidate = str(text).strip().lower().rstrip(":").replace("the ", "").strip()
    return candidate in FOCUSED_WORDS or candidate.startswith("focused")


@dataclass
class EditRequest:
    """One edit, in the form a model (or a recipe) can produce."""

    operation: str = EditOperation.SET.value
    value: str = ""
    old: str = ""
    new: str = ""
    marker: str = ""
    occurrence: str = "all"     # "all" | "first" | "last"
    note: str = ""

    def normalised(self) -> "EditRequest":
        alias = _OPERATION_ALIASES.get(self.operation.strip().lower())
        operation = alias or self.operation.strip().lower()
        if operation not in EDIT_OPERATIONS:
            operation = EditOperation.SET.value
        # `new` is the natural spelling for replace; accept `value` for it too.
        new = self.new if self.new != "" else (self.value if operation == EditOperation.REPLACE.value and self.old else self.new)
        return EditRequest(
            operation=operation,
            value=self.value,
            old=self.old,
            new=new,
            marker=self.marker,
            occurrence=self.occurrence if self.occurrence in ("all", "first", "last") else "all",
            note=self.note,
        )

    def describe(self) -> str:
        """A sentence for the panel log and the spoken status."""
        request = self.normalised()
        preview = lambda text: (text if len(text) <= 40 else text[:37] + "…")  # noqa: E731
        if request.operation == EditOperation.SET.value:
            return f"Replacing the whole field with {preview(request.value)!r}"
        if request.operation == EditOperation.APPEND.value:
            return f"Appending {preview(request.value)!r}"
        if request.operation == EditOperation.PREPEND.value:
            return f"Adding {preview(request.value)!r} at the start"
        if request.operation == EditOperation.REPLACE.value:
            return f"Replacing {preview(request.old)!r} with {preview(request.new)!r}"
        if request.operation == EditOperation.REMOVE.value:
            return f"Removing {preview(request.old)!r}"
        if request.operation in (EditOperation.INSERT_AFTER.value, EditOperation.INSERT_BEFORE.value):
            where = "after" if request.operation.endswith("after") else "before"
            return f"Inserting {preview(request.value)!r} {where} {preview(request.marker)!r}"
        return f"{request.operation.replace('_', ' ').capitalize()} the field"


def parse_edit_request(params: Dict[str, Any]) -> EditRequest:
    """Build an :class:`EditRequest` from loose model output."""
    return EditRequest(
        operation=str(params.get("operation") or params.get("op") or params.get("mode") or "set"),
        value=str(params.get("value") if params.get("value") is not None else params.get("text") or ""),
        old=str(params.get("old") or params.get("find") or params.get("search") or params.get("from") or ""),
        new=str(params.get("new") or params.get("replace") or params.get("to") or ""),
        marker=str(params.get("marker") or params.get("anchor") or ""),
        occurrence=str(params.get("occurrence") or params.get("which") or "all"),
        note=str(params.get("note") or ""),
    )


# --- the pure part: text in, text out --------------------------------------

def apply_edit(current: str, request: EditRequest) -> Tuple[str, str]:
    """Apply *request* to *current*.

    Returns ``(new_text, error)`` where *error* is empty on success.  This is a
    pure function on purpose: the interesting rules ("does appending respect a
    trailing newline?", "what happens when the marker is missing?") are decided
    here, with no screen, no clipboard and no input backend involved, and are
    covered by tests.
    """
    request = request.normalised()
    operation = request.operation

    if operation == EditOperation.SET.value:
        return request.value, ""

    if operation == EditOperation.CLEAR.value:
        return "", ""

    if operation == EditOperation.TRIM.value:
        return current.strip(), ""

    if operation == EditOperation.UPPER.value:
        return current.upper(), ""

    if operation == EditOperation.LOWER.value:
        return current.lower(), ""

    if operation == EditOperation.APPEND.value:
        if not current:
            return request.value, ""
        joiner = "" if current.endswith(("\n", " ", "\t")) or request.value.startswith(("\n", " ")) else " "
        return current + joiner + request.value, ""

    if operation == EditOperation.PREPEND.value:
        if not current:
            return request.value, ""
        joiner = "" if request.value.endswith(("\n", " ")) or current.startswith(("\n", " ")) else " "
        return request.value + joiner + current, ""

    if operation in (EditOperation.REPLACE.value, EditOperation.REMOVE.value):
        if not request.old:
            return current, "this edit needs the text to find (no 'old' was given)"
        replacement = "" if operation == EditOperation.REMOVE.value else request.new
        if request.old not in current:
            return current, f"the field does not contain {request.old!r}"
        if request.occurrence == "first":
            return current.replace(request.old, replacement, 1), ""
        if request.occurrence == "last":
            head, _, tail = current.rpartition(request.old)
            return head + replacement + tail, ""
        return current.replace(request.old, replacement), ""

    if operation in (EditOperation.INSERT_AFTER.value, EditOperation.INSERT_BEFORE.value):
        if not request.marker:
            return current, "this edit needs a marker to insert next to"
        if request.marker not in current:
            return current, f"the field does not contain the marker {request.marker!r}"

        before = operation == EditOperation.INSERT_BEFORE.value
        joiner = "\n" if "\n" in current else " "
        value = request.value

        starts: List[int] = []
        cursor = current.find(request.marker)
        while cursor != -1:
            starts.append(cursor)
            cursor = current.find(request.marker, cursor + len(request.marker))
        if request.occurrence == "first":
            starts = starts[:1]
        elif request.occurrence == "last":
            starts = starts[-1:]
        elif not request.occurrence == "all":
            starts = starts[:1]

        def splice(match_start: int) -> Tuple[int, str]:
            """Return ``(position, text)`` for this occurrence of the marker.

            The separator is decided by what is *already* on either side of the
            insertion point, so existing spacing is reused instead of doubled:

            * ``"Summary: lines here"`` + insert_after ``"Summary:"`` gives
              ``"Summary: NOTE lines here"``;
            * ``"a b c b d"`` + insert_before the last ``"b"`` gives
              ``"a b c X b d"``.

            Multi-line fields separate with a newline instead of a space.
            """
            position = (match_start + len(request.marker)) if not before else match_start
            left_char = current[position - 1:position]
            right_char = current[position:position + 1]
            left_ok = (not left_char) or left_char.isspace() or value[:1].isspace()
            right_ok = (not value) or (not right_char) or right_char.isspace() or value[-1:].isspace()
            prefix = "" if left_ok else joiner
            suffix = "" if right_ok else joiner
            return position, prefix + value + suffix

        updated = ""
        cursor = 0
        for match_start in starts:
            position, text = splice(match_start)
            position = max(cursor, min(position, len(current)))
            updated += current[cursor:position] + text
            cursor = position
        updated += current[cursor:]
        return updated, ""

    return current, f"unsupported edit operation {operation!r}"


@dataclass
class FieldReading:
    """What a field contained, and how sure we are."""

    text: str = ""
    source: str = ""          # "clipboard" | "ocr" | ""
    trustworthy: bool = False
    error: str = ""

    def __bool__(self) -> bool:
        return self.trustworthy


@dataclass
class EditOutcome:
    """The result of one read-modify-write cycle."""

    ok: bool = False
    message: str = ""
    before: str = ""
    after: str = ""
    expected: str = ""
    verified: bool = False
    changed: bool = False
    attempts: int = 0
    target: Optional[Tuple[int, int]] = None
    write_method: str = ""    # "paste" | "type"
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "before": self.before,
            "after": self.after,
            "expected": self.expected,
            "verified": self.verified,
            "changed": self.changed,
            "attempts": self.attempts,
            "write_method": self.write_method,
        }


# --- the part that touches the machine -------------------------------------

#: Written to the clipboard before a read so a *stale* clipboard can be detected.
SENTINEL = "naveed-clipboard-sentinel"
#: How long to wait, in total, for a copy/paste to be observable.
CLIPBOARD_TIMEOUT = 1.6
CLIPBOARD_POLL = 0.04
#: Hard cap on polling, so a clock that does not advance cannot hang a task.
MAX_CLIPBOARD_POLLS = max(8, int(CLIPBOARD_TIMEOUT / CLIPBOARD_POLL) + 8)
#: Above this length, pasting beats typing for both speed and fidelity.
PASTE_OVER_TYPING = 24


class FieldEditor:
    """Read-modify-write for a text field on screen.

    The controller is duck-typed; only these are used:

    ``move_to(x, y)`` · ``click(button="left", count=1)`` · ``type_text(text)`` ·
    ``press_key(key, modifiers=())`` · ``clipboard_text()`` · ``set_clipboard_text(text)``

    ``sleep`` and ``now`` exist so tests can run instantly and deterministically.
    """

    def __init__(
        self,
        controller: Any,
        *,
        locate: Optional[Callable[[Any, Optional[str]], Optional[Tuple[int, int]]]] = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
        clipboard_timeout: float = CLIPBOARD_TIMEOUT,
    ) -> None:
        self.controller = controller
        self.locate = locate
        self._sleep = sleep
        self._now = now
        self.clipboard_timeout = clipboard_timeout

    # --- clipboard ------------------------------------------------------
    def _read_clipboard(self) -> str:
        try:
            return self.controller.clipboard_text() or ""
        except Exception:
            return ""

    def _write_clipboard(self, text: str) -> bool:
        try:
            return bool(self.controller.set_clipboard_text(text))
        except Exception:
            return False

    @property
    def clipboard_available(self) -> bool:
        """Clipboard use only counts if a write is actually readable back."""
        marker = f"{SENTINEL}-probe"
        if not self._write_clipboard(marker):
            return False
        if self._read_clipboard() != marker:
            return False
        self._write_clipboard("")
        return True

    # --- targeting ------------------------------------------------------
    def _click_target(self, x: int, y: int, *, count: int = 1) -> None:
        move_to = getattr(self.controller, "move_to", None)
        if callable(move_to):
            move_to(int(x), int(y))
        click = getattr(self.controller, "click", None)
        if callable(click):
            try:
                click(button="left", count=count)
                return
            except TypeError:
                click()
        click_at = getattr(self.controller, "click_at", None)
        if callable(click_at):
            click_at(int(x), int(y), count=count)

    def _select_all(self) -> None:
        self.controller.press_key("a", ["ctrl"])

    def resolve_target(self, frame: Any = None, target: Optional[str] = None, point: Optional[Tuple[int, int]] = None) -> Optional[Tuple[int, int]]:
        """Find the field: explicit point, then the injected locator, then OCR."""
        if point is not None:
            return (int(point[0]), int(point[1]))
        if self.locate is not None:
            found = self.locate(frame, target)
            if found:
                return (int(found[0]), int(found[1]))
        return None

    # --- the cycle ------------------------------------------------------
    def read(
        self,
        point: Optional[Tuple[int, int]] = None,
        *,
        frame: Any = None,
        target: str = "",
        focused: bool = False,
    ) -> FieldReading:
        """Copy the field's exact contents out of it.

        With ``focused=True`` nothing is clicked: the text is taken from whatever
        already has the keyboard focus, which is the only safe way to edit a caret
        in an editor or a box that cannot be named.
        """
        if focused:
            point = None
        else:
            if point is None:
                point = self.resolve_target(frame, target)
            if point is None:
                return FieldReading(error="I could not find the field to read")
            self._click_target(*point)
        self._sleep(0.05)

        sentinel = f"{SENTINEL}-{uuid.uuid4().hex[:8]}"
        if not self._write_clipboard(sentinel):
            return FieldReading(error="the clipboard is not available, so I cannot read this field exactly")

        self._select_all()
        self._sleep(0.03)
        self.controller.press_key("c", ["ctrl"])

        deadline = self._now() + self.clipboard_timeout
        # Bounded twice over: by the clock *and* by an iteration cap.  A frozen or
        # coarse clock must not be able to hang a task, and this loop runs while
        # the user waits.
        for _poll in range(MAX_CLIPBOARD_POLLS):
            text = self._read_clipboard()
            if text != sentinel:
                return FieldReading(text=text, source="clipboard", trustworthy=True)
            if self._now() >= deadline:
                break
            self._sleep(CLIPBOARD_POLL)
        return FieldReading(
            error="the field did not respond to copy — it may not be a text field",
            source="clipboard",
        )

    def write(
        self,
        text: str,
        point: Optional[Tuple[int, int]] = None,
        *,
        frame: Any = None,
        target: str = "",
        focused: bool = False,
    ) -> Tuple[bool, str]:
        """Put *text* into the field and say which method was used."""
        if focused:
            point = None
        else:
            if point is None:
                point = self.resolve_target(frame, target)
            if point is None:
                return False, ""
            self._click_target(*point)
        self._sleep(0.05)
        self._select_all()

        long_enough_to_paste = len(text) > PASTE_OVER_TYPING
        if (long_enough_to_paste or "\n" in text) and self._write_clipboard(text):
            self._sleep(0.05)
            self.controller.press_key("v", ["ctrl"])
            self._sleep(0.08)
            # Fall through to the caller's verification; if pasting failed, the
            # read-back will notice and the retry will type instead.
            return True, "paste"

        if not text:
            self.controller.press_key("Delete")
            return True, "type"
        self.controller.type_text(text)
        return True, "type"

    def edit(
        self,
        request: EditRequest,
        *,
        frame: Any = None,
        target: str = "",
        point: Optional[Tuple[int, int]] = None,
        verify: bool = True,
        focused: bool = False,
    ) -> EditOutcome:
        """Read the field, apply *request*, write it back, verify, retry once."""
        request = request.normalised()
        outcome = EditOutcome(target=point)
        resolved: Optional[Tuple[int, int]] = None
        if not focused:
            resolved = self.resolve_target(frame, target, point)
            if resolved is None:
                outcome.message = "I could not find that field on the screen"
                return outcome
            outcome.target = resolved

        for attempt in (1, 2):
            outcome.attempts = attempt
            reading = self.read(resolved, focused=focused)
            if not reading.trustworthy:
                outcome.message = reading.error or "I could not read the current value of that field"
                return outcome
            outcome.before = reading.text

            updated, error = apply_edit(reading.text, request)
            if error:
                outcome.message = error
                outcome.details["hint"] = "the field may not contain what the request expected"
                return outcome

            outcome.expected = updated
            if updated == reading.text:
                outcome.ok = True
                outcome.verified = True
                outcome.changed = False
                outcome.message = "the field already said exactly that"
                return outcome

            written, method = self.write(updated, resolved, focused=focused)
            outcome.write_method = method
            if not written:
                outcome.message = "I could not write into that field"
                return outcome
            if not verify:
                outcome.ok = True
                outcome.message = "the field was updated (not verified)"
                return outcome

            check = self.read(resolved, focused=focused)
            outcome.after = check.text
            if check.trustworthy and check.text == updated:
                outcome.ok = True
                outcome.verified = True
                outcome.changed = True
                outcome.message = f"updated the field ({method})"
                return outcome

            # A paste that did not take is worth one more try as typing.
            if attempt == 1 and method == "paste" and not focused:
                point_still_valid = self.resolve_target(frame, target, resolved)
                if point_still_valid:
                    self._click_target(*point_still_valid)
                    self._select_all()
                    self.controller.type_text(updated)
                    check = self.read(point_still_valid)
                    outcome.after = check.text
                    outcome.write_method = "type"
                    if check.trustworthy and check.text == updated:
                        outcome.ok = True
                        outcome.verified = True
                        outcome.changed = True
                        outcome.message = "updated the field (typed, after pasting did not take)"
                        return outcome
            outcome.message = "the field did not keep what I wrote"
            outcome.details["before"] = reading.text[:400]

        return outcome

    # --- convenience used by the action handlers -------------------------
    def replace_value(
        self,
        value: str,
        *,
        frame: Any = None,
        target: str = "",
        point: Optional[Tuple[int, int]] = None,
        focused: bool = False,
    ) -> EditOutcome:
        return self.edit(
            EditRequest(operation=EditOperation.SET.value, value=value),
            frame=frame,
            target=target,
            point=point,
            focused=focused,
        )


def looks_like_field_label(text: str) -> bool:
    """Heuristic: does *text* read like the label of an editable field?

    Used by :mod:`naveed.skills` when a pack describes a form by its labels
    ("Summary", "Description", "Status") and Naveed has to choose among the OCR
    hits it found on screen.
    """
    if not text:
        return False
    cleaned = text.strip().rstrip(":*")
    if not cleaned or len(cleaned) > 40:
        return False
    if cleaned.endswith((".", ",", ";", "!", "?")) and " " in cleaned:
        return False
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9 _/\-()']*$", cleaned))
