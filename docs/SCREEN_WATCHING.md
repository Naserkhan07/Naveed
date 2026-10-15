# Watching the screen

Naveed does not poll the whole desktop and hope. It watches the way the reference
projects do, with the same constants where they were right and a few additions
where the problem demanded them.

## The pipeline

```
capture()  →  recover if empty  →  hash + signature  →  diff  →  world model
   │              │                    │                 │           │
   │              │                    │                 │           └─ state line for the planner
   │              │                    │                 └─ "did anything change?"
   │              │                    └─ "did it settle?" (loop protection)
   │              └─ "the grab failed" → platform fallback
   └─ mss | Qt | Pillow | macOS `screencapture`
```

### 1. Capture, with a chain of back-ends

`naveed/screen/capture.py` tries, in order:

| Back-end | Why it is in the chain |
|---|---|
| `mss` | Fastest, cross-platform, returns frames at monitor scale. |
| Qt (`QScreen.grabWindow`) | Already there when the UI is installed; works when `mss` is missing or blocked. |
| Pillow (`ImageGrab`) | Last resort on Windows/macOS. |
| `screencapture` (macOS) | Survives cases where `ImageGrab` returns an empty image on modern macOS. |

The chain is ported from brah's `src/screen-capture.js` and
`screen-capture-fallback.js`. Two of its rules were kept **verbatim in spirit**,
because they are the difference between a watcher that works and one that lies:

* **Empty-frame detection first.** A capture is handed to the fallback chain when
  it is missing, zero-sized, or entirely one colour. On macOS a missing Screen
  Recording permission does not raise — it returns an image of the wallpaper —
  so "the frame is not blank" has to be an explicit check.
* **4-pixel size tolerance** (`SIZE_TOLERANCE_PX = 4`). Retina/DPI rounding makes
  a requested 2560×1440 come back as 2560×1440±1, and treating that as a mismatch
  produced endless false "permission denied" paths. Real mismatches are still
  reported.
* **Never blame permissions when they are granted.** The original code contains a
  hard-won branch for exactly this; Naveed keeps the rule as a comment and a
  test, because a wrong permission message sends the user off to fix something
  that was never broken.

### 2. Diffing two frames

`naveed/screen/diff.py` — ported from OpenDesktop's `src/screen-state/index.js`.
Each frame becomes a small signature (a 64×36 greyscale grid) plus a 64-bit hash,
and two frames are compared on both:

```python
NOISE_FLOOR     = 0.02   # below this, it is just antialiasing and cursors
SCENE_THRESHOLD = 0.45   # above this, treat it as a different screen entirely
```

* `changed_fraction < NOISE_FLOOR` → **identical** (the cursor blinked, a
  caret moved). Measured on real frames here: 0 %, 0.33 % for a small noise
  change, 49.91 % for a scene change.
* `changed_fraction > SCENE_THRESHOLD` → **scene change**. Used by the agent to
  notice "a new window took over" and by the watcher to reset element continuity.
* In between → a normal, meaningful change, recorded as a state transition.

OpenDesktop records a new state when the difference clears its threshold
(`diffThreshold: 0.05` in the original). Naveed keeps the same shape but splits
the single threshold into the noise floor and the scene threshold, because the
agent needs both questions answered: *did anything change?* and *did everything
change?*

### 3. Adaptive cadence and settling

`naveed/screen/watch.py` runs on its own thread with a deliberately simple rule
set:

| Setting | Default | Meaning |
|---|---|---|
| `interval` | 2.0 s | Check this often while the screen is changing. |
| `idle_interval` | 6.0 s | Slow down to this when nothing is happening for a while. |
| `settle_after` | 3 | Frames that must be identical before the screen counts as *settled*. |
| `max_history` | 100 | Bounded world-model history — memory cannot grow without limit. |

Settling is what makes the agent reliable. After performing an action, Naveed
waits for the screen to stop moving *before* deciding whether the action worked;
otherwise it would compare a half-drawn page against the previous frame and
"discover" a change that was going to happen anyway.

### 4. The world model

`naveed/screen/state.py` keeps, for each recorded state: the timestamp, the
frame path, the focus context (app, window title, monitor), and the transitions
between states. From it the watcher derives a short **state line** for the
planner, which is what turns a screenshot into a situation:

```
on 'VS Code' (main.py — naveed), monitor 2 (2560×1440), quiet for 12s.
Screen mostly changed 4s ago (28% of pixels), then settled. 3 recent changes.
```

The planner is told what is *in front* and *what just happened*, so its answer can
depend on the flow of the work, not only on one frozen image.

## Coordinates: the part that is easy to get wrong

A screenshot is not a screen. `naveed/screen/displays.py` tracks each monitor's
origin, size **and scale**, and `naveed/screen/state.py::global_point` converts a
pixel in a captured image into a real desktop coordinate:

```
screen_x = monitor.x + (pixel_x / monitor.scale)
screen_y = monitor.y + (pixel_y / monitor.scale)
```

Tested cases that had to be right (they are asserted in `tests/test_screen.py`):

| Capture | Monitor | Pixel in image | Real coordinate |
|---|---|---|---|
| 5120×2880 (a full Retina grab) | scale 2.0, at x=1920 | (1280, 720) | (2560, 360) |
| 2560×1440 (a 1:1 grab of monitor 2) | scale 1.0(at x=1920) | (1280, 720) | (3200, 720) |

Two monitors at different scales, with the second starting at x=1920, is a
virtual desktop of `(0, 0, 4480, 1440)` — the mapping that a "just divide by 2"
implementation gets wrong.

**The rule taken from voice-computer-use-agent:** capture the monitor that shows
the target window, not all monitors, and keep that monitor's origin for the
conversion. Cropping a window out of a multi-monitor grab and then clicking at
the cropped coordinates is how an agent ends up clicking the wrong screen.

## Hiding from itself

The companion must not appear in the frames it reasons about, and must not eat
its own clicks:

* While capturing: the mascot is hidden (or, on Windows, excluded from the capture
  via `SetWindowDisplayAffinity`) and restored afterwards.
* While the agent is acting: the mascot is set click-through, so a click aimed at
  a button underneath it lands on the button.
* The panel is closed or click-through during a task for the same reason.

`naveed/overlay/window.py` exposes `hide_for_capture()`, `show_after_capture()`,
`set_click_through(on)` and `exclude_window_from_capture()`; the executor calls
them around capture and action phases, and every call is a no-op when Qt is not
available.

## Credit map

| Naveed file | Ported from | What changed |
|---|---|---|
| `screen/capture_fallback.py` | brah `src/screen-capture-fallback.js` | Rewritten around the capture-backend chain; kept empty-frame detection, the 4px tolerance and the permission rule. |
| `screen/capture.py` | brah `screen-capture.js` | Multi-backend order plus HiDPI-aware monitor selection. |
| `screen/retention.py` | brah `screenshot-retention.js`, `screenshot-list.js` | Explicit `prune()` (the original pruned inside its list call); never deletes the newest frame. |
| `screen/diff.py`, `screen/watch.py`, `screen/state.py` | OpenDesktop `src/screen-state/index.js` | Signature + hash comparison, adaptive interval, settling, bounded history, loop detection. |
| `screen/displays.py` | voice-computer-use-agent `vision_bridge.py` (`_capture_target`) | Monitor enumeration with scale and origin, Qt-assisted when available. |
| `screen/focus.py` | voice-computer-use-agent (`find_window`, focus helpers) | Per-platform window enumeration kept, with optional back-ends and no hard dependency. |
