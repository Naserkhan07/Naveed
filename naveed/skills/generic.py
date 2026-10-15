"""The general-purpose pack: editing anything, anywhere.

Polarion is one app. The user's ask was broader than that — *edit any task,
anywhere* — so this pack is the knowledge that applies to every application, with
no detection patterns at all: it is offered whenever nothing more specific
matches, which is exactly when generic advice is worth having.

It exists mostly to state the editing contract to the model in plain words, since
that contract is the difference between an assistant that edits your data and one
that overwrites it:

* read a field before you write to it (:func:`read_field` returns the *exact*
  text, not an OCR guess);
* change only the part that needs changing (`edit_field` with ``replace`` or
  ``append``, not ``set``);
* the field must show the new value afterwards, or the edit did not happen;
* if a field refuses typing it is usually read-only — say so, do not try harder.
"""

from __future__ import annotations

from typing import List

from .base import Recipe, RecipeStep, Skill

__all__ = ["SKILL", "build_skill"]

KNOWLEDGE = [
    "To change text that already exists, read it first, then change only what needs changing. Use edit_field with operation 'replace' (or 'append' / 'prepend' / 'insert_after') instead of 'set' — 'set' deletes everything else in the field.",
    "read_field copies the field's exact text out of the field: it is reliable where reading text off a screenshot is not.",
    "edit_field verifies itself. If it reports that the field did not keep what was written, the edit did NOT happen — do not claim success.",
    "A field that silently ignores typing is usually read-only, disabled, or locked by a workflow. Report that instead of retrying.",
    "For a long value, pasting is more accurate than typing; the paste path is used automatically. Typing is the fallback when a paste does not take.",
    "Typing into a search box, a filter or a toolbar field usually needs Enter afterwards to apply it.",
    "Prefer a targeted edit in place over navigating away, re-opening a record, and retyping it: in-place editing cannot lose the rest of the record.",
]

EDITING_TIPS = [
    "Locate a field by its visible label when you can (read_field/edit_field accept a target label); coordinates break as soon as the page scrolls.",
    "After any edit, re-read the field or take a fresh screenshot before moving on — the next click depends on what is actually there now.",
    "Use undo (ctrl+z) to back out of a wrong edit instead of editing again on top of it.",
    "Bulk edits (a selection in a table, a multi-record form) are worth confirming with the user first: the same mistake multiplied is much harder to undo.",
]

GOTCHAS = [
    "Do not retype an entire form to change one field.",
    "Do not edit a field that a previous step left focused unless you are sure the focus is still there.",
    "An unsaved edit is lost by navigating away, so save (or let the field's own save fire) before switching screens.",
]

GENERIC_RECIPES: List[Recipe] = [
    Recipe(
        name="edit-existing-value",
        description="change one occurrence of a value inside an existing field, keeping the rest intact",
        app="",
        skill="generic",
        params={"field": "the field's visible label", "old": "text to find", "new": "replacement"},
        steps=[
            RecipeStep(kind="edit_field", params={"target": "{{field}}", "operation": "replace", "old": "{{old}}", "new": "{{new}}", "occurrence": "first"}),
            RecipeStep(kind="wait", params={"seconds": 0.5}),
        ],
    ),
    Recipe(
        name="append-a-note",
        description="add a line to the end of an existing text field without losing it",
        app="",
        skill="generic",
        params={"field": "the field's visible label", "text": "the text to add"},
        steps=[
            RecipeStep(kind="edit_field", params={"target": "{{field}}", "operation": "append", "value": "{{text}}"}),
            RecipeStep(kind="wait", params={"seconds": 0.5}),
        ],
    ),
]

def build_skill() -> Skill:
    return Skill(
        id="generic",
        name="Editing anywhere",
        summary="Rules that apply to editing text in any application: read before writing, change only what needs changing, verify the result.",
        window_patterns=[],
        url_patterns=[],
        process_patterns=[],
        keywords=[],
        knowledge=list(KNOWLEDGE),
        shortcuts={},
        glossary={},
        gotchas=list(GOTCHAS),
        editing_tips=list(EDITING_TIPS),
        recipes=list(GENERIC_RECIPES),
        tools=[],
        source="built-in",
    )


SKILL = build_skill()
