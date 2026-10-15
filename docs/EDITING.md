# Editing what is already on screen

Naveed can change text that is already in a field, in any application: a browser
form, a Polarion work item, a spreadsheet cell, a text editor, a desktop app that
nothing else can reach. This document is how it works, why it is built this way,
and what it refuses to do.

The short version: **it reads the field first, works out the change on the text
it actually found, writes it back, and reads it again to check.** It never types
a value it has not verified, and it never reports success it has not confirmed.

---

## 1. The problem with typing

The obvious implementation — "click the field, select all, type the new value" —
loses information in three ways that all look like success:

| Failure | What the user sees |
| --- | --- |
| The field had content that was never read | Their text is gone, replaced by what the model guessed |
| The model retyped a long value from imperfect vision | Silent corruption: a word dropped, a number changed |
| The field is read-only (locked, workflow-protected) | The typing went nowhere and nobody noticed |

So the rule is: **no blind retyping.** If Naveed is going to change a value, it
must first know what the value *is*, character for character. That is what the
clipboard is for — it is the only channel from an arbitrary application to the
agent that is exact rather than approximate.

## 2. The read

```
read_field(target) →
    click the field (or focus it with the keyboard path from the pack)
    press Home / Ctrl+A to select what is there
    press Ctrl+C
    poll the clipboard, briefly, for a *changed* value
→ FieldReading(text, is_empty, selection_exact, how)
```

Details that matter:

* **A changed clipboard is the only proof of a copy.** If the clipboard did not
  change in `CLIPBOARD_TIMEOUT` (1.6 s, polled every 40 ms), the read failed —
  the field may have been empty, or the app may ignore Ctrl+C. An unchanged
  clipboard is never interpreted as "the field was empty".
* **Sentinels are preserved.** The pre-read value is saved, and if the clipboard
  still holds it afterwards the read is reported as failed rather than guessed.
* **Clocks cannot hang.** Polls are capped by `MAX_CLIPBOARD_POLLS`, so a frozen
  or mocked clock returns "could not read" instead of looping forever.
* **Empty is a legitimate answer**, reported as `is_empty=True` rather than an
  error, and the exact text `""`.

## 3. The change

`apply_edit(text, operation, …)` is a **pure function**: same input, same output,
no display, no clipboard, no timing. That is what makes the whole engine
testable, and it is why the semantics below are exactly the semantics in
`tests/test_editing.py`.

| Operation | Meaning |
| --- | --- |
| `set` | Replace the whole value. Explicitly destructive to anything else in the field. |
| `append` | Add to the end, preserving what is there. |
| `prepend` | Add to the beginning. |
| `replace` | Replace a specific substring — the surgical edit. |
| `remove` | Delete a specific substring. |
| `insert_after` / `insert_before` | Insert next to an anchor. **Whitespace-aware**: `insert_after("Summary:")` puts the text after the existing spacing, it does not concatenate blindly. `occurrence` selects which match when the anchor appears more than once. |
| `clear` | Empty the field. |
| `trim`, `upper`, `lower` | Normalise in place. |

Two behaviours are deliberate and are the ones most likely to surprise:

* **A missing anchor is not an error that damages anything.** `replace`,
  `remove`, `insert_after` and `insert_before` all require their anchor to be
  present. If it is not, the *original text is returned unchanged* along with the
  reason. Nothing is written, nothing is half-written.
* **`apply_edit` never writes to the clipboard or the screen.** It computes a
  string. The writing is a separate, verifiable step.

## 4. The write and the verification

```
edit_field(target, operation, text/value, occurrence) →
    read the field again (the current truth, not the older read)
    compute the new value with apply_edit
    if the value is unchanged, stop and say so
    write it:  paste it when the new value is long (PASTE_OVER_TYPING = 24 chars),
               type it when it is short, so a paste-in-progress cannot land late
    save the field the way *this* app saves (per-field, or one form-level Save)
    read it back
→ EditOutcome(changed=True, verified=True, before=…, after=…)
```

Verification is a real read, not an assumption: the field is read back through
the same clipboard path and compared with the value that was supposed to land.
If it does not match, that is reported:

* one retry as plain typing (some rich-text and canvas widgets accept typing but
  mangle a paste);
* then an honest failure — "the field did not keep the new value" — naming what
  it holds instead. Locked and workflow-protected fields are *supposed* to
  behave this way; the answer is to report the lock, never to type harder.

## 5. Locating the field

Fields are named, not coordinate-guessed, wherever the app allows it:

1. an explicit coordinate, if the model or the recipe knows one;
2. a `target` label resolved through OCR (`_resolve_target_point`) — the nearest
   text on screen that looks like a field label (`looks_like_field_label`);
3. **the field that already has the keyboard focus**, when there is nothing to
   click at all;
4. the pack's own route for the app (Polarion's per-field save buttons, the
   `ctrl+s` classic form, and so on — see `docs/POLARION.md`).

### 5.1 Aiming at the focused field

Some of the places people actually edit have no field to address — a caret in an
editor pane, a browser's contenteditable, a spreadsheet cell you just opened. The
model can ask for *there* instead of naming a target:

```json
{"type": "edit_field", "target": "focused", "operation": "replace", "find": "3", "value": "4"}
```

`is_focused_target()` decides whether a target means "whatever is focused"
(`focused`, `current`, `focused field`, `this field`, `selection`, `cursor`,
`caret`, `here`, …). The rule is strict, and it is the reason this does not break
the normal case:

* an explicit `global_point` (or `x`/`y`) always wins — a click is a click;
* a concrete `target` label or `element` behaves exactly as it always did;
* **only** when there is neither does `read_field` / `edit_field` skip the click
  and act on the control that already has focus, by marking the field as focused
  rather than aiming at it.

The alternative — clicking at the caret — is worse than doing nothing: a click on
empty space moves the caret, and a click that misses the window moves focus to
another app entirely. Not clicking is the only way to be sure the text that gets
edited is the text the user is looking at.

A dry run says so, in so many words, before anything happens:

```
would read the focused field
would edit the focused field: Replacing '3' with '4'
```

## 6. What the model is told, and what it is not asked to do

The planner prompt gets rules, not hints:

* read the field before editing it — never retype a value you have not read;
* prefer `edit_field` with `replace`/`append` over `set`;
* trust `edit_field`'s verification field instead of describing success;
* a read-only field is a fact to report, not an obstacle to retry through;
* if the pack lists a direct tool or a known routine that fits, use it.

## 7. Safety

Editing is not outside the safety system, and it is not a loophole in it:

* `read_field`, `read_screen`, `find`, `select_all` are `SAFE` — and reading is
  never a way to harvest secrets: a field whose *own label* names it as a
  credential (`password`, `passcode`, `PIN`, `CVV`, `token`, `secret`, `API key`,
  …) is refused for reads as well as writes, and the refusal says to type it
  yourself. A value that merely *looks* secret-shaped (a long random token) is
  caught by `looks_like_secret_value` before it is ever written, while a
  documented placeholder (`set-your-own`, `hunter2`) still round-trips, because a
  safety rule that blocks legitimate edits gets switched off in a week;
* `edit_field`, `clear`, `paste`, `undo`, `save` are classified as writes and go
  through the same guard as any other write — `WRITE_KINDS` covers every action
  kind that writes text, so a newly added kind cannot quietly skip the check;
* the secret guard scans the text that is about to be typed or pasted, so a
  password cannot be carried into a field by an edit;
* every step of a replayed routine is checked individually: a recorded routine is
  shorthand, not a permission.

## 8. Testing it

Everything above is covered by `tests/test_editing.py` (55 tests) without a
display, a clipboard or a window:

* `apply_edit` is tested as a pure function, including the awkward cases
  (`occurrence="last"`, anchors that appear twice, whitespace around an anchor,
  anchors that are absent);
* the clipboard path is tested with `TickingClock` and a fake controller, so the
  "unchanged clipboard means a failed read" rule is verified rather than assumed;
* a full `read_field` → `edit_field` → verify cycle runs against `FakeField`,
  the same fixture the Polarion tests reuse for record-and-replay.

`python3 -m unittest discover -s tests` runs it with everything else.
