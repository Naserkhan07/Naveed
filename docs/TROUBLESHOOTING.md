# Troubleshooting

Start with the report — it checks each capability separately and tells you what
is missing and how to install it:

```bash
python -m naveed --check
```

```
Naveed 0.1.0
  python      3.11.2  (linux)
  config      /home/you/.naveed/config.env
  home        /home/you/.naveed
  model       qwen2.5vl:7b @ 127.0.0.1:11434  ✓ configured
  interface   ✓ PySide6 installed
  capture     backends: none
              screen access: granted
  input       backends: none
  ocr         none (optional)
  speech      microphone: no, stt: none, tts: none
  missing     capture backend (mss/Pillow)
              install: pip install "naveed[ui,capture,input]"
```

(the *interface* line says "installed" when PySide6 is importable, and *capture* /
*input* list every backend they can actually reach — an empty list there is the
answer to "why does nothing happen when it clicks?")

## The mascot does not appear

Ask the machine, not the internet:

```bash
python -m naveed --overlay-check
```

It reports Qt, the session, the screen and the window — and then says whether the
mascot came up:

```
  ✓ PySide6 6.8.1 imports
  ✓ QApplication up (platform plugin: xcb, created by this check)
    screen DP-1: 2560x1440 at 0,0  dpr 1.0
  mascot window: 260x260 at 1096,-232  (size 168, anchor below_camera)
    ✓ frameless
    ✓ always-on-top
    ✓ no-taskbar-entry
    ✓ translucent
  ✓ the mascot is on screen at 1096,-232, always on top, and the panel is up.
```

…and when it cannot, it names the one thing that is missing. `--overlay-check
--save shot.png` also writes `shot-mascot.png` and `shot-panel.png`: what the
windows actually contain, which is worth sending with any bug report.

| What it says | Cause and fix |
|---|---|
| *PySide6.QtWidgets is not installed … libGL.so.1* | The Qt package is there and its libraries are not: `sudo apt install libgl1 libglx-mesa0` (Linux), or `pip install --force-reinstall PySide6-Essentials` (Windows/macOS, where the wheel ships everything). `pip install` alone cannot fix a system library. |
| *libEGL.so.1 / libxkbcommon / libdbus-1 / libxcb-…* | Same shape, different package — the message prints the exact `apt`/`dnf` line for the one it found. |
| *the 'offscreen' (or 'minimal') platform plugin* | `QT_QPA_PLATFORM` is set to a headless plugin: Qt runs, and shows nothing. Unset it to see the mascot, and keep it only for tests. |
| *there is no DISPLAY and no WAYLAND_DISPLAY* | There is no desktop to draw on — a container or a server. Run Naveed on the host, or forward X11. |
| *the mascot is outside …* | A remembered position from a monitor that is no longer attached. Delete `~/.naveed/state/overlay.json`, or set `OVERLAY_ANCHOR=below_camera`. |
| *PySide6 6.12.x … known refcount bug* | Upstream, bisected here: the process aborts with `Fatal Python error: none_dealloc: deallocating None` once a few thousand gradient fills have gone through a `QPainter` — a few seconds of mascot animation at 45 fps. Install `pip install "PySide6-Essentials<6.12"` (the `ui` extra already carries that ceiling). |
| *the mascot window was created but is not visible* | `OVERLAY_START_HIDDEN=true` puts it in the tray: set it to `false`, or use the tray's *Show*. |
| Nothing at all, and `--check` says *interface: PySide6 missing* | `pip install "naveed[ui]"` — and note that Naveed will **not** open a browser page in its place: the window is the product. |

Smaller things, once the window is up:

| Symptom | Cause and fix |
|---|---|
| It is behind every window | Another app's always-on-top rule is winning. `OVERLAY_ALWAYS_ON_TOP=true` plus the panel's *pin* toggle re-applies it. On macOS, use full-screen or *Do Not Disturb* rather than a full-screen app's own space. |
| Nothing shows on native Wayland | Wayland hides global window positions by design, so the mascot can land somewhere useless. Run under XWayland (`QT_QPA_PLATFORM=xcb`), or add a compositor rule for "always on top". `--overlay-check` names the plugin in use. |
| No tray icon | Some desktops need `libayatana-appindicator3-1`. The tray is optional — the mascot and the hotkey do everything the menu does. |
| `QWidget: Must construct a QApplication before a QWidget` | Fixed in 0.2.0: the reusable `QApplication` is created before any widget. If you see it in an old checkout, `git pull`. |

## The browser page

The same bot is served at `http://127.0.0.1:8765` when you ask for it —
`python -m naveed --serve`, or `WEB_ENABLED=true` alongside the mascot. Plain
`python -m naveed` opens no port at all. [docs/BROWSER.md](BROWSER.md) is the full picture; the
failures worth knowing:

| Symptom | Cause and fix |
|---|---|
| The page loads but every action says *lost the connection* | The server stopped. Restart it; the page reconnects on its own. |
| `401` on everything | You bound beyond loopback (`--host 0.0.0.0`), so the token printed at startup is required: `http://host:8765/?token=…`. `--no-token` only for a network you trust. |
| The port is not the one you configured | It was taken, and the bot picked a free one instead of refusing to start. The URL it printed is the right one. |
| *Show mascot* does nothing | It starts `python -m naveed` as a second process; run that by hand to see the error, or `python -m naveed --overlay-check` for the full diagnosis. |
| It refuses every task with the model message | Deliberate: the page opens even when the model is dead, and says why instead of failing later. |

## "I could not reach my LLM API"

`--check` asks the endpoint whether it *answers*, so this is diagnosable before a
task fails:

```bash
python main.py --check
#   llm api     qwen2.5vl:7b @ 127.0.0.1:11434  ✓ configured
#               ✗ nothing is answering at http://127.0.0.1:11434/v1 (Connection refused)
```

| What it says | What to do |
|---|---|
| *nothing is answering at http://127.0.0.1:…* | The local server is not running: `ollama serve`, then `ollama pull qwen2.5vl:7b`. |
| *is answering, but 'x' is not in its model list* | The server is up with different models — `ollama list`, then `--setup --provider ollama --model <name>`. |
| *rejected the request (HTTP 401)* | That API wants a token: set `LLM_TOKEN` in `~/.naveed/config.env`, or switch to a local model (`--setup --provider ollama`). |
| *did not answer in 1.5s* | Slow or unreachable host (a VPN, a firewall, a sleeping machine). |

A task that cannot reach the model now stops immediately and says so, instead of
asking you a question nobody can answer.

## I clicked the bot and nothing happened

The panel should appear, and the caret should land in the task box (or listening
starts, when a microphone is available). If neither happens:

* the panel may have opened off screen — drag the mascot towards the middle and
  click again, or `OVERLAY_REMEMBER_POSITION=false` to reset its position;
* with no input backend (`--check` says *input: backends: none*) the click still
  works but nothing can be typed into another app: `pip install "naveed[input]"`;
* if it says *"I cannot hear you"*, there is no microphone — typing works the same.

## The agent clicks in the wrong place

1. Run `python -m naveed --portrait me.png` — if the mascot renders fine there, the
   UI is not the problem.
2. Check scaling: Naveed converts screenshot pixels using the monitor's scale
   factor. A mismatched `CAPTURE_TARGET` (capturing the whole desktop but acting
   as if one monitor) is the classic cause. Set `CAPTURE_TARGET=active_window` to
   let it capture only the monitor showing the target window, as
   voice-computer-use-agent does.
3. Look at the frame the model actually saw: `ls -t ~/.naveed/screenshots | head`
   and open the newest. If the image is black or shows only the wallpaper, go to
   the capture section below.

## Screenshots are black or empty

Naveed detects this and switches back-ends automatically, but the *cause* is
usually permissions:

| OS | Fix |
|---|---|
| macOS | System Settings → Privacy & Security → **Screen Recording** → enable your terminal. Restart the terminal fully (the permission is read at process start). |
| macOS, still black | `ImageGrab`/`screencapture` can return the wallpaper with no error. Naveed runs `screencapture -x` as a last resort — check `--check`'s capture line. |
| Windows | Usually fine. If you run under WSL, capture sees the Linux side only. |
| Linux | Needs X11. Under Wayland, `mss` cannot read other windows; run with `QT_QPA_PLATFORM=xcb`, or use a portal-enabled compositor. |
| Virtual machine / remote desktop | Some hypervisors block the GPU capture path. `CAPTURE_TARGET=primary` plus the Pillow back-end usually works. |

## "No input backend" — the agent plans but nothing happens

Naveed needs one of `pynput`, `pyautogui`, or a platform API to move your mouse.

```bash
pip install "naveed[input]"
```

On macOS also grant **Accessibility** (System Settings → Privacy & Security →
Accessibility). On Linux, mac and Wayland sessions may refuse synthetic input
entirely — that is a compositor policy, not a Naveed setting.

`--dry-run` tells you whether the planning side works while input is broken: it
prints every intended click and types nothing.

## Voice

| Symptom | Fix |
|---|---|
| *no microphone found* | `pip install "naveed[voice]"` and check `VOICE_STT=auto` in `config.env`. Naveed lists the devices it can see in `--check`. |
| It never stops listening | `VOICE_SILENCE_SECONDS` is how long a pause ends your sentence (default 1.0). Raise it in a noisy room. |
| No voice, or a robot voice | Install Piper for the good offline voice: `pip install "naveed[voice]"`, then `python -m naveed --setup --voice en_US-amy-medium`. Falling back to `espeak`/`say`/SAPI is expected when Piper is absent — the panel shows which engine is in use. |
| It speaks over itself | Only one utterance plays at a time; a new one cancels the previous. If you hear doubling, two Naveed instances are running. |

## The mascot swallows my clicks

During a task Naveed sets itself click-through, so this should not happen. If it
persists: the panel's *pin* and the mascot's *always on top* are separate
settings — unpin the panel first. `OVERLAY_SIZE` too large plus a small screen is
also worth checking.

## The task stops early

* *"nothing changed three times in a row"* — the model is clicking things that do
  nothing. Try a better vision model (`--setup --provider openai`) or give more
  context in the request ("use the search box at the top of the page").
* *step limit* — `AGENT_MAX_STEPS` (default 18).
* *time limit* — `AGENT_MAX_TASK_SECONDS` (default 240).
* Both are in `config.env`; raise them for long jobs.

## The model returns junk or JSON errors

Naveed already retries without JSON mode when an endpoint rejects it, and extracts
JSON from prose/markdown fences. If a model keeps failing, it is probably not
vision-capable. Working choices: `gpt-4o-mini`, `qwen2.5-vl-7b-instruct`,
`llava`, `qwen2.5vl:7b` on Ollama, `gemini-2.0-flash` via its OpenAI-compatible
endpoint.

## An edit "did not stick"

That message is the engine being honest, not failing: it read the field back and
the value had not changed. In order of likelihood:

* **The field is locked.** Polarion (and Jira, and plenty of others) make fields
  read-only in certain workflow states — an Approved requirement, a released item,
  a closed ticket. Nothing can be typed into it by hand either. Report the state
  rather than retrying. See [POLARION.md](POLARION.md).
* **The field was not focused.** If the click landed on the label instead of the
  input, the typing goes nowhere. A richer app sometimes needs a click plus a
  moment for the caret to settle; the pack's `EDITING THIS APP` notes say so for
  apps where it matters.
* **It is a rich-text or canvas editor.** Long values are pasted rather than typed
  (over 24 characters), which some canvas widgets mangle. The engine already
  retries once as plain typing, then stops and tells you what the field holds.
* **The screenshot was stale.** Coordinates come from the last frame; if the
  window moved between the frame and the click, the click landed somewhere else.
  Keep the target window in front while a task runs.

Nothing is ever "fixed" by typing harder, and an unverified edit is never reported
as a success.

## A taught routine does not work the way I recorded it

* **Replay repeats, it does not generalise.** The routine is the steps you
  demonstrated, with your values substituted. If the recorded run clicked the
  third row of a table, replay will click the third row.
* **Values became parameters.** `PROJ-1042`, an email address or a date in what you
  typed is turned into `{work_item_id}` / `{email}` / `{date}` and has to be given
  at replay time: `--run-recipe name --arg work_item_id=PROJ-1042`. `--recipes`
  lists each routine's arguments.
* **A click may have been anchored to a label.** If OCR is available, a click is
  stored with the text nearest to it, which is what lets the routine survive the
  window moving — but it also means the routine follows that label.
* Inspect it directly: `~/.naveed/skills/learned/<name>.json` is plain JSON. Edit
  it by hand if the recording was almost right, or delete it and record again.

If `--teach` printed *"recording needs the input extra (pynput)"* and exited, it
recorded nothing: install it with `pip install "naveed[input]"` and try again.

## Where the logs and data are

```
~/.naveed/
  config.env        your settings (plain text)
  logs/naveed.log   rotating, 2 MB × 3, with --debug for full detail
  screenshots/      frames Naveed kept, newest 100
  models/           downloaded voices / local model files
  state/            the watcher's world model, if persisted
  skills/           the knowledge packs, and learned/*.json — your routines
```

```bash
python -m naveed --debug            # verbose logging to the console too
tail -f ~/.naveed/logs/naveed.log
```

Deleting `~/.naveed` is always safe: Naveed recreates it, and `--setup` writes a
fresh config.
