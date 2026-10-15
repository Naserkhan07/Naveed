"""Editing: the rules, and the read-modify-write cycle.

Two halves:

* :func:`apply_edit` is pure — text in, text out — so every rule about what an
  edit should do (spacing around an insertion, "replace the last occurrence",
  what happens when the marker is missing) is asserted directly.
* :class:`FieldEditor` is exercised against a fake field and a fake clipboard,
  including the two failure modes that would otherwise corrupt a user's data:
  a field that ignores Ctrl+C (so a *stale* clipboard must not be trusted) and a
  field that drops what was pasted (so the write must be verified, and retried as
  typing, before anything is reported as done).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naveed.control.editing import (
    EditOperation,
    EditRequest,
    FieldEditor,
    apply_edit,
    is_focused_target,
    looks_like_field_label,
    parse_edit_request,
)


class ApplyEditTests(unittest.TestCase):
    """The pure rules."""

    def edit(self, current: str, **params):
        return apply_edit(current, EditRequest(**params))

    def test_set_replaces_everything(self):
        self.assertEqual(self.edit("old text", operation="set", value="new"), ("new", ""))

    def test_set_accepts_the_names_a_model_uses(self):
        for alias in ("overwrite", "write", "fill", "replace_all", "SET"):
            self.assertEqual(self.edit("old", operation=alias, value="new")[0], "new", alias)

    def test_append_adds_a_separator_only_when_needed(self):
        self.assertEqual(self.edit("hello", operation="append", value="world")[0], "hello world")
        self.assertEqual(self.edit("hello ", operation="append", value="world")[0], "hello world")
        self.assertEqual(self.edit("hello\n", operation="append", value="world")[0], "hello\nworld")
        self.assertEqual(self.edit("", operation="append", value="world")[0], "world")

    def test_prepend_mirrors_append(self):
        self.assertEqual(self.edit("body", operation="prepend", value="Title:")[0], "Title: body")
        self.assertEqual(self.edit(" body", operation="prepend", value="Title:")[0], "Title: body")
        self.assertEqual(self.edit("", operation="prepend", value="Title:")[0], "Title:")

    def test_replace_and_remove(self):
        self.assertEqual(self.edit("the cat sat", operation="replace", old="cat", new="dog")[0], "the dog sat")
        self.assertEqual(self.edit("the cat sat", operation="remove", old=" cat")[0], "the sat")
        self.assertEqual(self.edit("cat cat cat", operation="replace", old="cat", new="dog", occurrence="first")[0], "dog cat cat")
        self.assertEqual(self.edit("cat cat cat", operation="replace", old="cat", new="dog", occurrence="last")[0], "cat cat dog")

    def test_replace_reports_a_missing_needle_instead_of_pretending(self):
        updated, error = self.edit("the cat sat", operation="replace", old="tiger", new="dog")
        self.assertEqual(updated, "the cat sat")
        self.assertIn("does not contain", error)

    def test_replace_needs_a_needle(self):
        _, error = self.edit("text", operation="replace", old="", new="x")
        self.assertIn("needs the text to find", error)

    def test_replace_accepts_the_value_key_for_the_replacement(self):
        # Models emit {"operation":"replace","old":"a","value":"b"} about as often
        # as they emit "new".
        self.assertEqual(self.edit("a b", operation="replace", old="a", value="c")[0], "c b")

    def test_insert_after_reuses_the_existing_spacing(self):
        self.assertEqual(
            self.edit("Summary: lines here", operation="insert_after", value="IMPORTANT", marker="Summary:")[0],
            "Summary: IMPORTANT lines here",
        )
        self.assertEqual(self.edit("a b c b d", operation="insert_after", value="X", marker="b")[0], "a b X c b X d")
        self.assertEqual(self.edit("head tail", operation="insert_after", value="X", marker="tail")[0], "head tail X")

    def test_insert_before_reuses_the_existing_spacing(self):
        self.assertEqual(
            self.edit("a b c b d", operation="insert_before", value="X", marker="b", occurrence="last")[0],
            "a b c X b d",
        )
        self.assertEqual(self.edit("head tail", operation="insert_before", value="X", marker="head")[0], "X head tail")

    def test_insert_in_a_multiline_field_uses_a_newline(self):
        self.assertEqual(
            self.edit("Summary:\nbody", operation="insert_after", value="NOTE", marker="Summary:")[0],
            "Summary:\nNOTE\nbody",
        )

    def test_insert_reports_a_missing_marker(self):
        updated, error = self.edit("body only", operation="insert_after", value="X", marker="Summary:")
        self.assertEqual(updated, "body only")
        self.assertIn("does not contain the marker", error)

    def test_clear_trim_and_case(self):
        self.assertEqual(self.edit("something", operation="clear")[0], "")
        self.assertEqual(self.edit("  padded  ", operation="trim")[0], "padded")
        self.assertEqual(self.edit("lower", operation="upper")[0], "LOWER")
        self.assertEqual(self.edit("UPPER", operation="lower")[0], "upper")

    def test_an_unknown_operation_falls_back_to_set_rather_than_mangling(self):
        # A confused model must not get a half-applied edit; "set" is the
        # operation with the most predictable outcome.
        self.assertEqual(self.edit("old", operation="frobnicate", value="new")[0], "new")

    def test_every_documented_operation_is_implemented(self):
        for operation in EditOperation:
            _, error = self.edit("sample text", operation=operation.value, value="v", old="text", new="w", marker="sample")
            self.assertEqual(error, "", f"{operation.value} failed: {error}")

    def test_describe_reads_like_a_sentence(self):
        self.assertIn("Appending", EditRequest(operation="append", value="x").describe())
        self.assertIn("Replacing the whole field", EditRequest(operation="set", value="x").describe())
        self.assertIn("'cat'", EditRequest(operation="replace", old="cat", new="dog").describe())

    def test_parse_edit_request_accepts_loose_model_output(self):
        request = parse_edit_request({"op": "add", "text": "more"})
        self.assertEqual(request.normalised().operation, "append")
        self.assertEqual(request.value, "more")
        request = parse_edit_request({"mode": "find_replace", "search": "a", "to": "b"})
        self.assertEqual(request.normalised().operation, "replace")
        self.assertEqual(request.old, "a")
        self.assertEqual(request.new, "b")


class FakeField:
    """A text field that behaves like a real one in the ways that matter."""

    def __init__(self, text: str = "", *, copies: bool = True, accepts_paste: bool = True, read_only: bool = False) -> None:
        self.text = text
        self.copies = copies              # False: ignores Ctrl+C (stale clipboard)
        self.accepts_paste = accepts_paste
        self.read_only = read_only        # a disabled/read-only field
        self.selected = False
        self.focused = False

    def focus(self) -> None:
        self.focused = True
        self.selected = False

    def select_all(self) -> None:
        self.selected = True

    def copy(self, clipboard: str) -> str:
        return self.text if (self.copies and self.selected) else clipboard

    def paste(self, clipboard: str) -> None:
        if self.accepts_paste and not self.read_only:
            self.text = clipboard

    def type(self, text: str) -> None:
        if self.read_only:
            return
        self.text = ("" if self.selected else self.text) + text
        self.selected = False


class FakeController:
    """The slice of the input controller plus clipboard that FieldEditor uses."""

    def __init__(self, field: FakeField) -> None:
        self.field = field
        self.clipboard = ""
        self.keys: list = []
        self.typed: list = []
        self.clicks: list = []
        self.moves: list = []

    # input controller surface
    def move_to(self, x, y):
        self.moves.append((x, y))
        self.field.focus()

    def click(self, button="left", count=1):
        self.clicks.append((button, count))
        self.field.focus()

    def click_at(self, x, y, count=1):
        self.click(button="left", count=count)

    def type_text(self, text):
        self.typed.append(text)
        self.field.type(text)

    def press_key(self, key, modifiers=()):
        self.keys.append((key, tuple(modifiers)))
        chord = (key.lower(), {modifier.lower() for modifier in modifiers})
        if chord == ("a", {"ctrl"}) or chord == ("a", {"cmd"}):
            self.field.select_all()
        elif chord == ("c", {"ctrl"}) or chord == ("c", {"cmd"}):
            self.clipboard = self.field.copy(self.clipboard)
        elif chord == ("v", {"ctrl"}) or chord == ("v", {"cmd"}):
            self.field.paste(self.clipboard)
        elif key == "Delete" and self.field.selected:
            self.field.text = ""
            self.field.selected = False

    # clipboard surface
    def clipboard_text(self):
        return self.clipboard

    def set_clipboard_text(self, text):
        self.clipboard = text
        return True


class TickingClock:
    """A clock that advances on every read, like a real one does.

    (``now=lambda: 0.0`` would freeze time and turn the clipboard poll into an
    infinite loop — the editor bounds that with an iteration cap as well, but a
    test double should model reality.)
    """

    def __init__(self, step: float = 0.05) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        self.value += self.step
        return self.value


def make_editor(text: str = "", **field_kwargs):
    field = FakeField(text, **field_kwargs)
    controller = FakeController(field)
    editor = FieldEditor(controller, sleep=lambda _seconds: None, now=TickingClock())
    return editor, controller, field


class FieldEditorReadTests(unittest.TestCase):
    def test_read_returns_the_exact_field_contents(self):
        editor, controller, _field = make_editor("Exact contents: 100% — ünïcode")
        reading = editor.read((10, 20))
        self.assertTrue(reading.trustworthy)
        self.assertEqual(reading.text, "Exact contents: 100% — ünïcode")
        self.assertEqual(reading.source, "clipboard")

    def test_a_field_that_ignores_copy_is_not_trusted(self):
        # The clipboard still holds the sentinel, so the read must fail rather
        # than return whatever happened to be on the clipboard.
        editor, _controller, _field = make_editor("hidden", copies=False)
        reading = editor.read((10, 20))
        self.assertFalse(reading.trustworthy)
        self.assertIn("did not respond to copy", reading.error)

    def test_read_without_a_target_explains_itself(self):
        editor, _controller, _field = make_editor("x")
        editor.locate = lambda frame, target: None
        reading = editor.read()
        self.assertFalse(reading.trustworthy)
        self.assertIn("could not find the field", reading.error)

    def test_clipboard_probe_detects_an_unavailable_clipboard(self):
        editor, controller, _field = make_editor("x")
        controller.set_clipboard_text = lambda text: False
        self.assertFalse(editor.clipboard_available)


class FieldEditorEditTests(unittest.TestCase):
    def test_set_is_written_and_verified(self):
        editor, _controller, field = make_editor("old value")
        outcome = editor.edit(EditRequest(operation="set", value="brand new"), point=(5, 5))
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue(outcome.verified)
        self.assertTrue(outcome.changed)
        self.assertEqual(outcome.before, "old value")
        self.assertEqual(outcome.after, "brand new")
        self.assertEqual(field.text, "brand new")

    def test_append_keeps_what_was_already_there(self):
        editor, _controller, field = make_editor("First line")
        outcome = editor.edit(EditRequest(operation="append", value="— second"), point=(1, 1))
        self.assertTrue(outcome.ok)
        self.assertEqual(field.text, "First line — second")

    def test_an_edit_that_changes_nothing_is_reported_as_already_true(self):
        editor, _controller, field = make_editor("same")
        outcome = editor.edit(EditRequest(operation="set", value="same"), point=(1, 1))
        self.assertTrue(outcome.ok)
        self.assertFalse(outcome.changed)
        self.assertIn("already said exactly that", outcome.message)

    def test_a_missing_marker_is_reported_and_nothing_is_written(self):
        editor, _controller, field = make_editor("body only")
        outcome = editor.edit(EditRequest(operation="insert_after", value="X", marker="Summary:"), point=(1, 1))
        self.assertFalse(outcome.ok)
        self.assertIn("does not contain the marker", outcome.message)
        self.assertEqual(field.text, "body only")

    def test_long_text_is_pasted_not_typed(self):
        editor, controller, _field = make_editor("short")
        long_text = "x" * 200
        outcome = editor.edit(EditRequest(operation="set", value=long_text), point=(1, 1))
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.write_method, "paste")
        self.assertEqual(controller.typed, [], "a long value should not be typed character by character")

    def test_short_text_is_typed(self):
        editor, _controller, field = make_editor("short")
        outcome = editor.edit(EditRequest(operation="set", value="tiny"), point=(1, 1))
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.write_method, "type")
        self.assertEqual(field.text, "tiny")

    def test_a_field_that_drops_the_paste_is_retried_as_typing(self):
        editor, _controller, field = make_editor("original", accepts_paste=False)
        outcome = editor.edit(EditRequest(operation="set", value="y" * 60), point=(1, 1))
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.write_method, "type")
        self.assertEqual(field.text, "y" * 60)

    def test_a_read_only_field_fails_honestly_instead_of_claiming_success(self):
        # A disabled or read-only field (very common in an approval workflow) must
        # produce an honest failure — never a message that says the edit landed.
        editor, _controller, field = make_editor("locked by the workflow", read_only=True)
        outcome = editor.edit(EditRequest(operation="set", value="ignored"), point=(1, 1))
        self.assertFalse(outcome.ok)
        self.assertIn("did not keep", outcome.message)
        self.assertFalse(outcome.verified)
        self.assertEqual(field.text, "locked by the workflow")

    def test_target_can_come_from_the_locator(self):
        editor, _controller, field = make_editor("findable")
        editor.locate = lambda frame, target: (42, 84) if target == "Description" else None
        outcome = editor.edit(EditRequest(operation="set", value="found"), target="Description")
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.target, (42, 84))
        self.assertEqual(field.text, "found")

    def test_outcome_serialises_for_the_panel_log(self):
        editor, _controller, _field = make_editor("a")
        payload = editor.edit(EditRequest(operation="set", value="b"), point=(1, 1)).as_dict()
        for key in ("ok", "message", "before", "after", "verified", "write_method"):
            self.assertIn(key, payload)


class LabelHeuristicTests(unittest.TestCase):
    def test_plausible_field_labels(self):
        for label in ("Summary", "Description:", "Work Item ID", "Status", "Assign to / Owner"):
            self.assertTrue(looks_like_field_label(label), label)

    def test_sentences_and_junk_are_not_labels(self):
        for label in ("", "  ", "This is a long sentence that goes on and on and on.", "Click here to continue.", None):
            self.assertFalse(looks_like_field_label(label), repr(label))


class ControllerIntegrationTests(unittest.TestCase):
    """The action handlers, exercised through OsController.perform."""

    def setUp(self):
        from naveed.config import load_config
        from naveed.control.os_control import OsController

        self.field = FakeField("Original")
        self.controller = FakeController(self.field)
        self.os = OsController(load_config(), input_controller=self.controller)
        self.os.global_point = lambda action, frame=None, **kwargs: (100, 200)

    def perform(self, payload):
        from naveed.control.actions import normalize_action

        return self.os.perform(normalize_action(payload))

    def test_edit_field_action_changes_the_field_and_reports_it(self):
        result = self.perform({"type": "edit_field", "x": 100, "y": 200, "operation": "append", "value": "text"})
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.field.text, "Original text")
        self.assertTrue(result.payload["verified"])

    def test_read_field_action_returns_the_text_to_the_model(self):
        self.field.text = "the current description"
        result = self.perform({"type": "read_field", "x": 100, "y": 200})
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.payload["text"], "the current description")
        self.assertEqual(result.payload["characters"], len("the current description"))

    def test_read_field_fails_politely_when_the_field_ignores_copy(self):
        self.field.copies = False
        result = self.perform({"type": "read_field", "x": 100, "y": 200})
        self.assertFalse(result.ok)
        self.assertIn("respond to copy", result.message)

    def test_edit_field_reports_a_bad_edit_instead_of_claiming_success(self):
        result = self.perform({"type": "edit_field", "x": 1, "y": 2, "operation": "replace", "old": "missing", "new": "x"})
        self.assertFalse(result.ok)
        self.assertIn("does not contain", result.message)
        self.assertEqual(self.field.text, "Original")

    def test_select_all_find_undo_save_and_paste_are_real_chords(self):
        self.perform({"type": "select_all"})
        self.perform({"type": "find", "text": "work item"})
        self.perform({"type": "undo", "times": 2})
        self.perform({"type": "save"})
        self.perform({"type": "paste"})
        chords = [(key.lower(), set(modifiers)) for key, modifiers in self.controller.keys]
        self.assertIn(("a", {"ctrl"}), chords)
        self.assertIn(("f", {"ctrl"}), chords)
        self.assertEqual(chords.count(("z", {"ctrl"})), 2)
        self.assertIn(("s", {"ctrl"}), chords)
        self.assertIn(("v", {"ctrl"}), chords)
        self.assertIn("work item", self.controller.typed)

    def test_find_without_text_is_refused(self):
        result = self.perform({"type": "find"})
        self.assertFalse(result.ok)
        self.assertIn("needs the text", result.message)

    def test_edit_actions_are_blocked_from_typing_secrets(self):
        # The credential rule has to cover the new write path, not just `type`.
        result = self.perform(
            {"type": "edit_field", "x": 1, "y": 2, "operation": "set", "value": "sk-abcdef0123456789abcdef0123456789"},
        )
        self.assertTrue(result.blocked, result.message)
        self.assertIn("secret", result.message.lower())

    def test_a_bare_pin_is_blocked_in_a_credential_field(self):
        result = self.perform({"type": "edit_field", "x": 1, "y": 2, "operation": "set", "value": "4821", "label": "Password"})
        self.assertTrue(result.blocked, result.message)

    def test_editing_a_description_that_mentions_deleting_is_not_blocked(self):
        # Editing ordinary prose must not trip the destructive-keyword guard:
        # the intent lives in the user's request, not in the field's contents.
        self.field.text = "We had to delete the old requirement"
        result = self.perform(
            {"type": "edit_field", "x": 1, "y": 2, "operation": "append", "value": "and re-add it later"},
        )
        self.assertTrue(result.ok, result.message)
        self.assertIn("re-add it later", self.field.text)

    def test_a_hard_blocked_command_is_still_refused_in_a_field(self):
        result = self.perform({"type": "edit_field", "x": 1, "y": 2, "operation": "set", "value": "sudo rm -rf /"})
        self.assertTrue(result.blocked, result.message)


class EditingAnywhereTests(unittest.TestCase):
    """Editing has to reach the caret too, not only a field you can name.

    "Edit anything anywhere" fails in exactly one situation if it can only act on a
    discovered target: the text is right in front of the user — a caret in a code
    editor, a rich-text box inside a dialog, a cell that was just opened — and
    there is no label to search for. Clicking a guessed point there is how you
    edit the wrong thing, so the editor can work on whatever has focus and click
    nothing at all.
    """

    def test_the_focused_vocabulary_is_recognised(self):
        for word in ("", None, "focused", "the focused field", "this field", "current", "cursor", "here", "selection"):
            self.assertTrue(is_focused_target(word), word)

    def test_a_real_label_is_not_mistaken_for_focus(self):
        for label in ("Status", "Description", "Summary", "the Title field", "work item id"):
            self.assertFalse(is_focused_target(label), label)

    def test_read_from_focus_clicks_nothing(self):
        editor, controller, field = make_editor("already open in an editor")
        reading = editor.read(focused=True)
        self.assertTrue(reading.trustworthy)
        self.assertEqual(reading.text, "already open in an editor")
        self.assertEqual(controller.clicks, [], "reading the focused field must not click anything")
        self.assertEqual(controller.moves, [])

    def test_read_from_focus_still_reports_a_field_that_ignores_copy(self):
        editor, controller, field = make_editor("locked", copies=False)
        reading = editor.read(focused=True)
        self.assertFalse(reading.trustworthy)
        self.assertIn("respond to copy", reading.error)
        self.assertEqual(controller.clicks, [])

    def test_edit_from_focus_changes_only_what_was_asked_and_verifies(self):
        editor, controller, field = make_editor("A description with one typo in it")
        outcome = editor.edit(
            EditRequest(operation="replace", old="one typo", new="no typos"),
            focused=True,
        )
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue(outcome.verified)
        self.assertEqual(field.text, "A description with no typos in it")
        self.assertEqual(controller.clicks, [], "the caret was already in place")

    def test_edit_from_focus_reports_missing_text_honestly(self):
        editor, controller, field = make_editor("nothing like that here")
        outcome = editor.edit(EditRequest(operation="replace", old="absent", new="x"), focused=True)
        self.assertFalse(outcome.ok)
        self.assertIn("does not contain", outcome.message)
        self.assertEqual(field.text, "nothing like that here")


class FocusedTargetDecisionTests(unittest.TestCase):
    """Which of the three ways to address a field wins."""

    def setUp(self):
        from naveed.config import load_config
        from naveed.control.actions import normalize_action
        from naveed.control.os_control import OsController

        self.action = normalize_action
        self.os = OsController(load_config(), input_controller=FakeController(FakeField("")))

    def wants_focus(self, payload):
        return self.os._wants_focused_field(self.action(payload), None)

    def test_coordinates_win(self):
        self.assertFalse(self.wants_focus({"type": "edit_field", "x": 10, "y": 20, "operation": "append", "value": "x"}))

    def test_a_label_wins(self):
        self.assertFalse(self.wants_focus({"type": "edit_field", "target": "Description", "operation": "append", "value": "x"}))

    def test_nothing_means_the_focused_field(self):
        self.assertTrue(self.wants_focus({"type": "edit_field", "operation": "append", "value": "x"}))
        self.assertTrue(self.wants_focus({"type": "read_field"}))
        self.assertTrue(self.wants_focus({"type": "read_field", "target": "focused"}))


class FocusedActionTests(unittest.TestCase):
    """The same thing, through the action layer the model actually calls."""

    def setUp(self):
        from naveed.config import load_config
        from naveed.control.os_control import OsController

        self.field = FakeField("the field the caret is in")
        self.controller = FakeController(self.field)
        self.os = OsController(load_config(), input_controller=self.controller)

    def perform(self, payload):
        from naveed.control.actions import normalize_action

        return self.os.perform(normalize_action(payload))

    def test_edit_field_without_a_target_edits_the_focused_field(self):
        result = self.perform({"type": "edit_field", "operation": "append", "value": " plus more"})
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.field.text, "the field the caret is in plus more")
        self.assertEqual(self.controller.clicks, [])

    def test_read_field_without_a_target_reads_the_focused_field(self):
        result = self.perform({"type": "read_field"})
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.payload["text"], "the field the caret is in")
        self.assertEqual(self.controller.clicks, [])

    def test_a_dry_run_says_which_field_it_would_touch(self):
        from naveed.config import load_config
        from naveed.control.os_control import OsController

        config = load_config()
        config.safety.dry_run = True
        os_control = OsController(config, input_controller=self.controller)
        result = os_control.perform(
            __import__("naveed.control.actions", fromlist=["normalize_action"]).normalize_action(
                {"type": "edit_field", "operation": "append", "value": "x"}
            )
        )
        self.assertTrue(result.ok, result.message)
        self.assertIn("the focused field", result.message)
        self.assertTrue(result.payload.get("dry_run"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
