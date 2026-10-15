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

| Symptom | Cause and fix |
|---|---|
| `--check` says *interface: not installed* | `pip install "naveed[ui]"` |
| Crash mentioning `libGL.so.1` | Qt needs OpenGL. `sudo apt install libgl1 libegl1 libxkbcommon-x11-0`. In a container without a GPU, use `QT_QPA_PLATFORM=offscreen` (it will run, invisibly). |
| Runs, but nothing shows on Linux/Wayland | Wayland hides global windows by design. Use XWayland (`QT_QPA_PLATFORM=xcb`), or your compositor's "always on top" rule. |
| It is behind every window | Another app's always-on-top rule is winning. `OVERLAY_ALWAYS_ON_TOP=true` plus the panel's *pin* toggle re-applies it. On macOS, use full-screen or *Do Not Disturb* rather than a full-screen app's own space. |
| No tray icon | Some desktops need `libayatana-appindicator3-1`. The tray is optional — the mascot and the hotkey do everything the menu does. |

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
