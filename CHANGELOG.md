# Changelog

What changed, in the order it landed. Versions are the package version
(`naveed.__version__`); the date is the day the work was pushed.

## 0.3.0 — the LLM is an API, not a key

The headline is a subtraction: **there is no API key anywhere in Naveed any more.**
The model is reached as an LLM *API* — a base URL and a model name — which is what
it always was technically, and what the documentation, the config file and the
settings panel now say. A local server (the default) needs no credential at all; a
hosted gateway that insists on an `Authorization` header reads an optional
`LLM_TOKEN`, which Naveed never asks for.

### Changed — configuration

* `LLMSettings` is `base_url` + `model` + optional `token`. Nothing is required but
  an endpoint: `configured` is true when a URL and a model name are set.
* `LLM_API` and `LLM_MODEL` are the environment variables (the old
  `OPENAI_BASE_URL` / `NAVEED_MODEL` still work); `LLM_TOKEN` exists only for
  gateways that demand one. Settings files written by Naveed now emit
  `LLM_API=` / `LLM_MODEL=` / `LLM_TOKEN=`.
* `--setup` no longer asks for a key, and `python -m naveed --setup` with no
  provider writes a working local default.
* New `--api URL [--model NAME] [--token TOKEN]`: any OpenAI-compatible endpoint,
  including one you host yourself, without a preset.
* The settings panel lost its key field; the status line reads `llm api
  <model> @ <host>`, and `--check` asks the endpoint whether it answers.
* `examples/config.env.example`, `README.md`, `docs/TROUBLESHOOTING.md` and
  `docs/SAFETY.md` were re-worded to match. A test loads the shipped example and
  fails if it names a setting that does not exist.

### Added — editing what is already there

* **Focused-field editing.** With no clickable target — a caret in an editor, a
  contenteditable, a cell you just opened — `read_field` / `edit_field` act on the
  control that *already has keyboard focus*, without clicking at all. A click is
  still what an explicit point or target means; only when there is neither does
  focus decide the field, because clicking at a caret moves it.
* **"Edit this" quick action** in the panel and the browser page: read the exact
  current value, change only what needs changing, keep the formatting, verify, and
  report.
* `docs/EDITING.md` § 5.1 documents the rule and the dry-run wording.

### Added — Polarion

* `python -m naveed --polarion-check`: prints the pack's API/project/access state,
  then performs **one** cheap `getWorkItems?...&limit=1` and reports the verdict as
  a sentence (a wrong token says wrong token, a wrong project says wrong project).
  Never raises, never writes.
* `python -m naveed --train NAME [--countdown SECONDS] [--skill PACK]`: `--teach`
  with the pack's tips printed first and a countdown (Ctrl-C cancels) before
  recording starts.
* `naveed/skills/polarion.py` gained `api_status()` and `api_probe()`, both of which
  return sentences rather than exceptions.

### Safety

* A field whose *label* names it as a credential is now refused for **reads** as
  well as writes — a secret guard that only covers typing is half a guard.
* A credential inside a larger payload (`password=hunter2-xyz`) is refused, while a
  documented placeholder (`api_key: set-your-own`) stays editable: the check is on
  the value's shape, not on the word.

## 0.2.0 — the bot you can also open in a browser

### The browser front end (new)

* `naveed/server.py` + `naveed/webui.py`: the same bot served over HTTP, standard
  library only, one self-contained page, no CDN and no build step.
* `python -m naveed --serve` runs it with no window at all (so a machine without
  PySide6 is a supported machine); `naveed-web` is the same as a console script.
* `python -m naveed` / `python main.py` now bring up the mascot **and** the page,
  sharing one `AgentBridge`: a task typed in the browser moves the mascot, and the
  screen is still captured once.
* Endpoints: `GET /`, `/api/health`, `/api/state?since=N` (numbered events),
  `/api/screen`; `POST /api/task`, `/api/answer`, `/api/cancel`, `/api/recipe`,
  `/api/overlay`, `/api/quit`. `POST /api/task` refuses an unreachable model with
  the same sentence the CLI prints, instead of queueing work that cannot run.
* Loopback by default; a token is required when bound wider (`--host 0.0.0.0`),
  compared with `hmac.compare_digest`; `--no-token` for a container port on a
  network you trust. A busy port falls back to a free one instead of failing.
* `docs/BROWSER.md`, and the browser sections in `SAFETY.md` and
  `TROUBLESHOOTING.md`.

### Fixed — the overlay

* `QWidget: Must construct a QApplication before a QWidget`: the single
  `QApplication` is created before any widget exists.
* pynput's hotkey thread and the speech threads touched Qt widgets directly; they
  now emit through two new `_Relay` signals (`wake`, `voice_state`). This is the
  bug class that made the panel silently fail to appear.
* The mascot starts **below the camera** and remembers where it was dragged
  (clamped fully back on screen if that monitor is gone).
* The panel no longer opens on top of the mascot: with the mascot at the top of
  the screen the "above" anchor had nowhere to go and clamped onto the character.
  It flips to whichever side fits, for every anchor.
* Clicking the mascot opens the panel and puts the caret in the task box when
  there is no microphone to listen with.

### Fixed — the headless path

* An unreachable model used to be reported as `[failed] I asked: … (no answer yet)`
  after the task budget expired. Now `ActionPlan.error` travels to the task, the
  task fails immediately, and the message names the reason (`WinError 10061`,
  "nothing is answering at http://127.0.0.1:11434/v1") and the fix.
* `--check` asks the endpoint whether it is **answering** (`LLMClient.probe`), not
  merely configured, and `run_task` refuses before it starts planning.
* `main.py` (new, repo root): the double-clickable launcher. Finds Naveed from any
  directory, writes a first config only when a model is obviously reachable,
  prints one short block of hints, and passes every other flag through.

### Edit anything on screen (new)

* `read_field` → compute the change → `edit_field` → save → **read it back to
  verify**, in any app, by pixel target or by OCR label.
* Operations: `set`, `append`, `prepend`, `replace`, `remove`, `insert_after`,
  `insert_before`, `clear`, `trim`, `upper`, `lower` — whitespace-aware, with one
  retry as plain typing when the clipboard write is refused, and an honest failure
  on a read-only or locked field.
* `docs/EDITING.md`.

### Teach it your app (new)

* Knowledge packs: facts, window patterns, keyboard shortcuts, editing regions and
  routines per application, matched to the focused window and injected into the
  prompt within a fixed budget (3600 chars).
* A Siemens **Polarion** pack with 11 facts, 8 shortcuts, 4 routines and 4 tools —
  including a REST fast path (`SKILLS_POLARION_*`), which reads work items
  directly and only enables writes when you set `SKILLS_ALLOW_API_WRITES=true`.
* `--teach NAME` records a demonstration (pynput), distils it into a **routine**,
  and suggests which values should become parameters; `--run-recipe` replays it
  with no model at all, every step still checked by the safety guard.
* Deliberately **no fine-tuning**: a routine is data, so it is inspectable, fixable
  and reviewable. `--export-training` exists for people who want a dataset anyway.
* `docs/POLARION.md`.

### Tests

286 tests, ~21 s, no display and no model required; `pyflakes naveed/ tests/
main.py` clean. New suites: `tests/test_server.py` (the HTTP surface, on real
sockets), `tests/test_launcher.py` (the launcher and the packaging), and
`tests/test_editing.py` (the edit engine as a pure function).

## 0.1.0 — the floating companion

* The transparent, frameless, always-on-top mascot with the glass control panel,
  idle float/blink and the listening → thinking → executing → speaking states.
* The screen watcher (adaptive interval, change signature, bounded world model),
  which is where the brah, OpenDesktop and voice-computer-use-agent code landed.
* The task loop: plan → act → verify → report, with the safety guard, budgets, the
  destructive-action confirmation and the dry run.
* Offline voice on both ends (Whisper/Vosk in, Piper out) and the tray, hotkeys
  and quick actions around them.
