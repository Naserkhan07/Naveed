# Actions: the vocabulary the model speaks

The planner never emits code, shell commands or free-form prose that something
downstream has to interpret. It emits **actions** from a closed vocabulary of 31
kinds (`naveed/control/actions.py::ACTION_KINDS`), each carrying pixel
coordinates in the screenshot it was shown.

```json
{
  "understanding": "The user wants YouTube opened and searched for lo-fi.",
  "summary": "Focus the browser and use the search box.",
  "actions": [
    {"type": "open_url", "url": "https://www.youtube.com"},
    {"type": "click", "x": 720, "y": 128, "note": "the search box"},
    {"type": "type", "text": "lo-fi beats", "note": "then press Enter"},
    {"type": "key", "key": "Enter"}
  ],
  "done": false,
  "question": null
}
```

`understanding` — what Naveed thinks is on the screen.
`summary` — what this step intends to do (it is fed back on the next step, so the
model can see that its last action achieved nothing).
`done` — ends the task, with the final sentence taken from `summary`.
`question` — set when the model needs the human; it becomes an `ask`.

## The kinds, and the fields each one reads

| Kind | Fields | What it does |
|---|---|---|
| `click` | `x`, `y` · or `target`/`element` | Clicks a point in the last screenshot (OCR resolves `target` when no coordinates are given). |
| `double_click` | `x`, `y` | Two quick clicks — opens files, selects words. |
| `right_click` | `x`, `y` | Context menu. |
| `middle_click` | `x`, `y` | Middle button (opens links in a background tab). |
| `move` | `x`, `y` | Moves the pointer without clicking, for hover menus. |
| `drag` | `path` *or* `x`, `y` + `to_x`, `to_y` | Press, move along a humanised path, release. |
| `scroll` | `amount` (or `dy`), `dx`, `x`, `y` | Scrolls at a point; negative is up. |
| `type` | `text` (or `value`) | Types text — secrets are refused, see [SAFETY.md](SAFETY.md). |
| `key` | `key` + `modifiers`/`keys` | One key or chord, e.g. `{"type":"key","key":"s","modifiers":["ctrl"]}`. |
| `hotkey` | `hotkey` *or* `keys` | A chord as a string or list, e.g. `["ctrl","shift","t"]`. |
| `wait` | `seconds` (0.05–30, default 1) | Pauses for the screen to catch up. |
| `screenshot` / `look` | — | Takes a fresh frame; `look` is the same thing, from the quick-action vocabulary. |
| `open_url` | `url` (or `target`) | Opens a URL in the default browser; a bare domain gets `https://`. |
| `open_app` | `app` (or `name`/`target`) | Launches an application, platform-appropriate. |
| `open_file` | `path` (or `file`/`target`) | Opens a file or folder with its default handler. |
| `focus_window` | `title` (or `app`/`target`) | Brings a window to the front. |
| `shell` | `command`, `timeout` | Runs a command — **off unless `SAFETY_ALLOW_SHELL=true`**, allowlistable, always checked by the hard-block table. |
| `clipboard_get` | — | Reads the clipboard (result goes back to the model). |
| `clipboard_set` | `text` (or `clipboard`) | Copies text to the clipboard. |
| `ask` | `question` | Asks the human and *waits* for the answer. |
| `done` | `summary` | Ends the task with that sentence. |
| `read_field` | `target` (label) *or* `x`, `y`, or `target: "focused"`; `key`, `modifiers` | Clicks the field, selects everything, copies, and returns the **exact** current text. The only honest way to know what a field contains. With `focused` (and no point) it reads whichever control already has keyboard focus, **without clicking** — the only way to read a caret in an editor. |
| `edit_field` | `target` *or* `x`, `y`, or `target: "focused"`; `operation`, `text`/`value`, `old`/`new`, `occurrence`, `save` | Reads the field, computes the change, writes it back, saves it, then **reads it back to verify**. `focused` edits where the caret already is (again: no click, so the caret cannot move). See [EDITING.md](EDITING.md) for the operations. |
| `select_all` | `target` *or* `x`, `y` | Selects the whole field/document body (`ctrl+a` in context). |
| `find` | `text`, `target` *or* `x`, `y` | Opens the app's own find bar and searches — jumping to a value beats scrolling to it. |
| `undo` | `times` (default 1) | `ctrl+z` — the escape hatch when an edit went wrong. |
| `save` | `hotkey`, `target` *or* `x`, `y` | Saves the current document or field, the way the app saves (`ctrl+s`, or a Save button). |
| `paste` | `text` (or `clipboard=false` to paste what is already there) | Types anything long via the clipboard rather than key-by-key — faster and exact. |
| `recipe` | `name`, `args` | Runs a known routine (a recorded demonstration, or a built-in one). Expanded into real, individually safety-checked steps before anything runs — see [POLARION.md](POLARION.md). |
| `skill_tool` | `skill`, `tool`, `args` | Calls a knowledge pack's own tool, e.g. Polarion's REST API. Only offered when that pack's tools are configured; a tool that writes automatically requires confirmation. |

`note` is free text on any action and is what the panel's log and the spoken
status use — write it as the sentence you would say to a person.

## Forgiving input, strict output

A language model will not spell things the same way twice, so `Action.from_dict`
accepts aliases and normalises them, and `ActionKind` accepts `"type"` or
`"kind"` as the discriminator:

```
left_click • single_click           → click
dblclick • doubleclick              → double_click
mouse_move • movemouse              → move
write • type_text • typing • text   → type
press • press_key • keypress        → key
keys • combo                        → hotkey
sleep • pause                       → wait
capture • screen                    → screenshot
look_at_screen • analyze_screen     → look
launch • start_app • open_application → open_app
browse • open_link • goto • navigate → open_url
switch_window • activate_window     → focus_window
terminal • run • command            → shell
finish • complete                   → done
answer                              → ask
replace_text • append_text          → edit_field
macro                               → recipe
tool                                → skill_tool
read • get_field • read_value       → read_field
```

Key names get the same treatment in `naveed/control/keys.py`, one shared alias
table ported from brah's `computer-use-actions.js`:

```python
canonical_hotkey(["ctrl", "shift", "t"])               → ("ctrl", "shift", "t")
canonical_hotkey("cmd+space")                          → ("cmd", "space")   # ⌘ on macOS
canonical_hotkey({"key": "Enter", "modifiers": ["ctrl"]}) → ("ctrl", "enter")
normalize_key("ENTER")                                 → "enter"
```

`modifiers` may be a string or a list; `keys` may be a string (`"ctrl+shift+t"`)
or a list. Missing numbers stay `None` rather than becoming `0`: a click at
(0, 0) is a real click in the corner, and silently defaulting to it caused a very
confusing bug during development.

## Coordinates, and why they are always pixels

`x`/`y` are pixels **in the image the model was shown**, never desktop
coordinates. Conversion happens exactly once, in
`naveed/screen/state.py::global_point`:

```python
screen_x = monitor.x + (pixel_x / monitor.scale)
screen_y = monitor.y + (pixel_y / monitor.scale)
```

The planner's system prompt says so in these words: *"coordinates are pixels in the
image I am showing you; do not adjust for scaling yourself."* Giving the same rule
to the model and to the conversion is what stops a Retina laptop from being off by
a factor of two.

When the model gives a `target` instead of coordinates, `_resolve_target_point`
asks OCR (`naveed/control/ocr.py`) for the text, takes the centre of its box and
converts it through the same monitor. **With no OCR available the action fails
with an explanation rather than clicking somewhere random** — a small model
guessing coordinates is worse than an honest error.

## The 14 planner rules

`naveed/agent/prompts.py::PLANNER_SYSTEM` states, in order:

1. Look at the screenshot; describe what you see before deciding.
2. Prefer direct routes — `open_url`, `open_app`, `hotkey` — over hunting for a
   browser icon with the mouse.
3. Never type secrets (passwords, one-time codes, access tokens, card numbers).
4. Never emit shell commands.
5. At most 4 actions per step.
6. Coordinates are pixels in the shown image; name the element in `note`.
7. Do not repeat an action that produced no change — that is why the previous
    `summary` and result are sent back with each step.
8. Use `ask` when genuinely blocked, `done` when finished.
9. `wait` after anything that loads.
10. If the request cannot be done on this screen, say so with `done` and an
    explanation instead of inventing clicks.
11. **To change text that already exists, `read_field` first, then `edit_field`.**
    Never retype a whole field to change part of it — `set` deletes everything
    else in it.
12. `edit_field` proves its own work. If it reports the value did not stick, the
    edit did not happen — say so instead of assuming success.
13. A field that ignores typing is read-only or workflow-locked: report it, and do
    not try the same field three times.
14. If the app's notes list a tool or a routine that fits, use it (`skill_tool`,
    `recipe`) — it is more reliable than clicking.

Two rules deserve the emphasis they get in the prompt: number 11 (read before you
edit) and number 12 (an edit is only done when it has been read back and verified).
Blind retyping is the single most damaging thing a computer-use agent can do — it
silently replaces text it never read — and a confident "done" after a write that
did not stick is the second. Both are handled in the engine rather than trusted to
the model: see [EDITING.md](EDITING.md).

The planner is wrapped so a model failure can never crash a task: a timeout, an
HTTP error or unparseable output becomes an empty plan plus a status message, and
the loop applies its no-change rule. `extract_json` copes with markdown fences,
leading prose and trailing commas, because models produce all three.
