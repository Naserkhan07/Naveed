# Architecture

Naveed is one long-lived process made of six layers and two front ends. Each layer
is importable and testable on its own, and the layers only talk through small,
plain-Python interfaces.

```
   ┌──────────────────────────────────────────────────────────────┐
   │ overlay/   the visible companion (Qt)                        │
   │  window · panel · tray · hotkeys · bridge (Qt signals)       │
   ├──────────────────────────────────────────────────────────────┤
   │ server.py · webui.py   the same bot over HTTP (stdlib only)  │
   └───────────────▲──────────────────────────┬───────────────────┘
                   │ status/say/action events │ clicks, typed tasks
   ┌───────────────┴──────────────────────────▼───────────────────┐
   │ agent/     the brain                                         │
   │  llm · prompts · planner · executor · bridge                 │
   └───────▲──────────────┬───────────────────────────┬───────────┘
           │ frames       │ actions                   │ speech
   ┌───────┴────────┐  ┌──▼─────────────────┐  ┌───────▼──────────┐
   │ screen/        │  │ control/           │  │ speech/          │
   │ capture·diff·  │  │ keys·input·actions·│  │ audio·tts·stt·   │
   │ watch·state    │  │ safety·os_control  │  │ loop             │
   └───────▲────────┘  └────────────────────┘  └──────────────────┘
           │
   ┌───────┴──────────────────────────────────────────────────────┐
   │ lazy.py + config.py + render/   the floor every layer stands on│
   └──────────────────────────────────────────────────────────────┘
```

## The rules

**1. Lazy imports, everywhere.** `naveed/lazy.py` is the foundation.

| Never | Always |
|---|---|
| `import mss` at module level | `mss = lazy.load("mss", extra="capture")` inside the function that captures |
| `from PIL import Image` at tops of files | `Image = lazy.load("PIL.Image", extra="capture")` next to the drawing code |
| Qt imported by anything but `overlay/` and `render/qt_canvas.py` | `QtWidgets = lazy.load("PySide6.QtWidgets", extra="ui")` inside the widget factory |

The contract, enforced by `tests/test_overlay.py` in a **fresh interpreter**:
importing every package in the project must leave `PySide6`, `PIL`, `mss`,
`numpy`, `pynput`, `sounddevice`, `faster_whisper`, `piper` and `pyttsx3` absent
from `sys.modules`. This is what makes `naveed --check` work on a machine where
almost nothing is installed, and it is why building the mascot's *facade*
imports no Qt at all — only `window.build()` does.

`lazy.load(name, extra=...)` raises `MissingDependencyError`, whose message names
the feature and the fix:

```
mss is required for screen capture.  Install it with:
    pip install "naveed[capture]"      (or: pip install mss)
```

`lazy.optional(name)` returns `None` instead, for "use it if it is there".
Optional machinery must always degrade, never raise: a broken Qt install means
`PySide6` is reported missing in `--check`, not a traceback at startup.

**2. One canvas, two back-ends.** `naveed/render/canvas.py` defines a tiny
drawing protocol — `rect`, `circle`, `line`, `polygon`, `gradient`, `radial`,
`text`, `fit` — with `#RRGGBB[AA]` colours. Two implementations exist:

* `qt_canvas.QtCanvas` — a `QPainter` (the live window);
* `pillow_canvas.PillowCanvas` — a PIL image (previews, tests, exports).

The mascot, the icons and the panel mock are written against the protocol, never
against Qt or Pillow. `<a name="why-a-canvas-abstraction"></a>`

Why this matters: the environment Naveed was built in has **no display and no
`libGL.so.1`, so Qt cannot start there at all**. Without the abstraction, the
character's geometry would have been unverifiable — write it, ship it, hope. With
it, `python -m naveed --portrait` renders the real paint code through Pillow, the
pixel tests in `tests/test_visual.py` assert the palette, symmetry, expressions
and transparency, and the images in the README are the same code the live window
runs. The Qt back-end is then a thin, boring translation of the same calls.

The two back-ends do have one real difference, and it is a bug worth remembering:
**compositing a transparent shape over an opaque one is a no-op on both**. That
is why the gear icon is drawn as teeth + a stroked ring rather than "a disc with
a hole punched out", and why `gradient(..., radius=)` clips the gradient's own
alpha (`ImageChops.multiply`) instead of overwriting it — an overwrite turned a
14-alpha glass highlight into a solid white slab across the panel.

**3. Threads for work, signals for delivery.** The agent loop blocks, so it runs on
a worker thread (`naveed/agent/bridge.py::AgentBridge`). Qt widgets may only be
touched from the GUI thread, so results cross back through a `QObject` carrying
signals (`naveed/overlay/bridge.py::_Relay`). The bridge itself knows nothing
about Qt: it takes callbacks (`on_status`, `on_say`, `on_action`, `on_question`,
`on_finish`) and the overlay supplies them. That is why the whole task loop can be
tested headlessly with `tests/fakes.py`.

**4. Everything the agent does is an *action*.** A closed vocabulary of 31 kinds in
`naveed/control/actions.py`, each carrying pixels in the screenshot it was planned
from. The planner emits JSON, `Action.from_dict` accepts messy variants, and
`OsController.perform` is the only place that touches the real machine. Adding a
capability means adding a kind and its handler — not touching the loop.

**5. Nothing about the machine leaks upward.** `Config` merges defaults →
`~/.naveed/config.env` → `NAVEED_*` environment → dotted CLI overrides, and every
module takes the settings object it needs. There are no module-level singletons
to reset between tests.

## The data flow of one task

```python
# 1. something asks for a task (click, hotkey, panel, CLI, or a quick action)
bridge.submit("open youtube and search for lo-fi beats")

# 2. the bridge starts a worker and returns immediately
# 3. the worker (AgentBridge._work) calls, blocking:
agent.run(prompt)                     # naveed/agent/executor.py

# 4. inside the loop, per step:
frame = watcher.capture_now()         # screen/capture.py + capture_fallback
state = watcher.world_summary()       # screen/state.py — what changed, what settled
context = agent._skill_context(task, window)  # skills/base.py — the app's notes, once
plan  = planner.plan(prompt, frame, state, history, context)   # agent/planner.py
#   → a {"type":"recipe",...} action is expanded here into its real steps, and a
#     routine's steps are then treated exactly like the model's own
#   → {"understanding": "...", "summary": "...", "actions": [...], "done": false}

# 5. each action is inspected, then performed
verdict = safety.inspect(action, raw_text)            # control/safety.py
if verdict.needs_confirmation:  ask the human, wait, timeout denies
result  = controller.perform(action, frame)           # control/os_control.py
#   → InputController clicks/keys via pynput|pyautogui|quartz, in real pixels

# 6. verification: the screen must change, unless the plan says otherwise
watcher.wait_until_settled()
if frame_hash_after == frame_hash_before: no_change_streak += 1
#   → 3 in a row means "stop, tell the user, ask for help"

# 7. the loop ends on done / failure / budget / cancellation, and every event has
#    already been streamed to the UI through the bridge callbacks
```

## Why the pieces are where they are

| File | Belongs there because |
|---|---|
| `screen/capture_fallback.py` | Empty-frame recovery is a *capture* concern: it decides whether a grab failed and how to retry it, before any other layer sees a frame. |
| `screen/diff.py`, `screen/state.py` | Change detection and the world model are pure functions over frames — no I/O, so they are trivially testable and cannot block. |
| `control/keys.py` | Key names arrive from a language model, so normalisation belongs at the boundary, in one shared table (ported from brah's `computer-use-actions.js`). |
| `control/safety.py` | The guard must sit between "decided" and "performed". If it lived inside the executor, a second caller could bypass it. |
| `agent/planner.py` | Prompt work is separate from loop work: the planner can be replaced (a local model, a smarter model) without touching verification or budgets. |
| `agent/bridge.py` | The bridge is the *only* place that knows about threads, so the agent stays synchronous and testable. |
| `overlay/bridge.py` | The Qt signal relay is the only place that knows about Qt's thread rules. |
| `server.py` | The HTTP front end wraps the *existing* `BridgeEvents` instead of the bridge learning about the web, so the agent still knows nothing about its front ends — and the browser can run in the same process (sharing one bridge) or on its own, on a machine with no Qt. |
| `control/editing.py` | The edit engine is separate from the actions that use it, and `apply_edit` is a *pure function*, so the semantics of `replace`/`insert_after`/`append` are testable without a screen, a clipboard or a clock. |
| `skills/base.py` | A pack is data (facts, shortcuts, recipes, tools) with one matching rule, so a new app is a new file and not a new branch in the agent. |
| `skills/recorder.py` | Recording is a *listener* on the input side, so it can be started and stopped from the UI without the agent knowing it exists; distilling is a pure function over the recorded events. |

## Testing strategy

* **Pure layers, real assertions.** Diff thresholds, monitor mapping, key
  normalisation, safety verdicts, JSON extraction: all tested directly.
* **Fakes over mocks.** `tests/fakes.py` provides a `FakeWatcher` (a scripted
  sequence of frames and world states) and a `FakeController`, so the agent's
  *behaviour* is tested — including "the click did nothing, so it tried something
  else" — not its call sequence.
* **A subprocess for the import contract**, because lazy imports can only be
  judged in a fresh interpreter.
* **Pixels for the art.** Symmetry, palette, expression distinctness and
  transparency are asserted numerically, so a change to the mascot that "looks
  fine" in one place but breaks the character fails the suite.
* **A stubbed network for the REST tools.** The Polarion tests replace the one
  function that touches `urllib`, so error mapping (401/403/404, unreachable
  server, empty and non-JSON bodies) is asserted without a server — and the
  transport tests stub the socket instead, to check the headers and the id →
  project resolution that a stubbed transport would hide.

Run it all:

```bash
python -m unittest discover -s tests -v
```
