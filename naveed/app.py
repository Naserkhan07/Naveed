"""Application façade: one object that owns config, watcher, agent and overlay.

The CLI (``python -m naveed``) is a thin shell around this class, and so is the
optional ``python -m naveed.overlay``.  Keeping the wiring here means there is
exactly one place that decides what "starting Naveed" means, which matters
because there are three quite different ways to run it:

``overlay``   the normal one: mascot on screen, panel, tray, voice;
``agent``     headless single task (``--prompt "do X"``) — how you test the loop
              without a display, and how a power user scripts it;
``watch``     headless screen watching only (``--watch``), useful for debugging
              capture on a new machine.

Everything is built lazily, and every optional subsystem (voice, tray, OCR,
input, GUI) is allowed to be missing.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import __version__, lazy
from .config import Config, PROVIDER_PRESETS, load_config, write_env_file

logger = logging.getLogger("naveed.app")

__all__ = ["NaveedApp", "describe_environment", "install_hint_text"]


class NaveedApp:
    """Owns the pieces and starts/stops them as a unit."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or load_config()
        self.overlay: Optional[Any] = None
        self.bridge: Optional[Any] = None
        #: set to True by the stop hotkey while recording a demonstration
        self._teach_stop = False
        #: tasks finished in this session, for --export-training
        self.recent_tasks: List[Any] = []

    # --- reporting --------------------------------------------------------
    def describe(self) -> Dict[str, Any]:
        """Environment and capability report (``--check``)."""
        return describe_environment(self.config)

    def print_report(self, stream=None) -> None:
        """Human-readable version of :meth:`describe`."""
        stream = stream or sys.stdout
        report = self.describe()
        print(f"Naveed {__version__}", file=stream)
        print(f"  python      {report['python']}  ({report['platform']})", file=stream)
        print(f"  config      {report['config_file'] or '(defaults — none written yet)'}", file=stream)
        print(f"  home        {report['home']}", file=stream)
        print(f"  model       {report['model']}  {'✓ configured' if report['model_ready'] else '✗ no key/local server'}", file=stream)
        if not report["model_ready"]:
            print("              add one:  python -m naveed --setup --provider ollama", file=stream)
        print(f"  interface   {'✓ PySide6 installed' if report['ui'] else '✗ PySide6 missing (no mascot)'}", file=stream)
        print(f"  capture     backends: {', '.join(report['capture_backends']) or 'none'}", file=stream)
        print(f"              screen access: {report['screen_access']}", file=stream)
        print(f"  input       backends: {', '.join(report['input_backends']) or 'none'}", file=stream)
        print(f"  ocr         {', '.join(report['ocr']) or 'none (optional)'}", file=stream)
        print(f"  speech      microphone: {'yes' if report['speech']['microphone'] else 'no'}, "
              f"stt: {', '.join(report['speech']['transcribers']) or 'none'}, "
              f"tts: {', '.join(report['speech']['tts_engines']) or 'none'}", file=stream)
        missing = report["missing_required"]
        if missing:
            print(f"  missing     {', '.join(missing)}", file=stream)
            print('              install: pip install "naveed[ui,capture,input]"', file=stream)

    # --- running modes ------------------------------------------------------
    def run_overlay(self, *, prompt: Optional[str] = None) -> int:
        """Start the floating companion (the normal way to run Naveed)."""
        from .overlay.bridge import OverlayApp

        self.overlay = OverlayApp(self.config)
        self.bridge = self.overlay.bridge
        if prompt:
            self.overlay.bridge.submit(prompt)
        try:
            return self.overlay.run()
        except lazy.MissingDependencyError as error:
            print(error, file=sys.stderr)
            print(install_hint_text(), file=sys.stderr)
            return 2
        finally:
            try:
                self.bridge.stop()
            except Exception:
                pass

    def run_task(self, prompt: str, *, verbose: bool = True) -> int:
        """Run one task headlessly and print what happened."""
        from .agent.bridge import AgentBridge, BridgeEvents

        events = BridgeEvents(
            on_status=lambda state, detail="": _echo(verbose, f"  [{state}] {detail}"),
            on_say=lambda text: _echo(verbose, f"  say: {text}"),
            on_action=lambda result: _echo(
                verbose,
                f"  action: {result.action.describe()} -> {'ok' if result.ok else 'failed'}: {result.message[:100]}",
            ),
            on_question=lambda question: _echo(verbose, f"  question: {question}"),
            on_error=lambda message: _echo(verbose, f"  error: {message}"),
        )
        bridge = AgentBridge(self.config, events=events)
        self.bridge = bridge
        bridge.start()
        try:
            if not bridge.model_ready:
                print(install_hint_text(), file=sys.stderr)
            bridge.submit(prompt)
            # Wait for the worker to finish (no GUI event loop here).
            deadline = time.time() + float(self.config.agent.max_task_seconds) + 60.0
            while bridge.busy and time.time() < deadline:
                time.sleep(0.2)
            task = bridge.last_task
            if task is None:
                time.sleep(0.5)
                task = bridge.last_task
            if task is None:
                reason = getattr(bridge, "last_error", "") or "the worker never started one"
                print(f"no task ran — {reason}", file=sys.stderr)
                return 1
            print(f"\n{task.status.value.upper()}: {task.result}")
            for step in task.steps:
                marker = "✔" if step.get("ok") else "✕"
                print(f"  {step.get('step')}. {marker} {step.get('description', '')} — {step.get('message', '')}")
            return 0 if task.status.value == "done" else 1
        finally:
            bridge.stop()


    # --- knowledge packs, recipes and teaching ---------------------------
    def show_skills(self, *, verbose: bool = True) -> int:
        """List the packs Naveed has been taught, and what is in them."""
        from .skills.base import SkillStore

        store = SkillStore(self.config).load()
        rows = store.summaries()
        if not rows:
            print("no knowledge packs are loaded", file=sys.stderr)
            return 1
        print(f"Naveed knows {len(rows)} app pack(s)  (from {store.directory}):\n")
        for row in rows:
            print(f"  {row['id']} — {row['name']}   [{row['source']}]")
            if row["summary"]:
                print(f"      {row['summary']}")
            if row["window_patterns"]:
                print(f"      detected by: {', '.join(row['window_patterns'])}")
            print(f"      {row['knowledge']} facts")
            for recipe in row["recipes"]:
                print(f"      routine: {recipe}")
            for tool in row["tools"]:
                print(f"      tool:    {tool}")
            print()
        extra = [recipe for recipe in store.all_recipes() if recipe.learned]
        if extra:
            print(f"{len(extra)} routine(s) learned by demonstration live in {store.directory / 'learned'}")
        if store.errors:
            print("problems while loading packs:", file=sys.stderr)
            for error in store.errors:
                print(f"  - {error}", file=sys.stderr)
        api_ready = bool(self.config.skills.polarion_base_url)
        print(
            "\nAPI fast path: "
            + ("configured" if api_ready else "not configured (Naveed will drive the UI instead)")
            + ("" if self.config.skills.allow_api_writes else "  · API writes are OFF (set SKILLS_ALLOW_API_WRITES=true to enable)")
        )
        return 0

    def show_recipes(self) -> int:
        """List every routine, with the arguments each one takes."""
        from .skills.base import SkillStore

        store = SkillStore(self.config).load()
        recipes = store.all_recipes()
        if not recipes:
            print("no routines yet — record one with: python -m naveed --teach <name>")
            return 1
        print("Routines (run one with --run-recipe <name> --arg key=value):\n")
        for recipe in recipes:
            origin = "learned" if recipe.learned else "built-in"
            owner = f" [{recipe.skill}]" if recipe.skill else ""
            print(f"  {recipe.signature()}{owner}  ({origin})")
            if recipe.description:
                print(f"      {recipe.description}")
            if recipe.params:
                for name, description in recipe.params.items():
                    default = recipe.defaults.get(name)
                    suffix = f" (default: {default})" if default not in (None, "") else ""
                    print(f"      --arg {name}=…  {description}{suffix}")
            print(f"      {len(recipe.steps)} steps")
            print()
        return 0

    def run_recipe(self, name: str, arguments: Dict[str, str], *, verbose: bool = True, dry_run: bool = False) -> int:
        """Run a recorded routine directly — no model required.

        This is the payoff of teaching: the steps are Naveed's own, so replaying
        them needs no planning model at all. That makes a demonstrated task work
        offline, on a machine with no API key, and identically every time.
        """
        from .agent.bridge import AgentBridge
        from .skills.base import SkillStore

        store = SkillStore(self.config).load()
        recipe = store.find_recipe(name)
        if recipe is None:
            print(f"there is no routine called {name!r} — see --recipes", file=sys.stderr)
            return 1
        missing = recipe.missing_arguments(arguments)
        if missing:
            print(f"{recipe.name} needs: {', '.join(missing)}", file=sys.stderr)
            print(f"  example: python -m naveed --run-recipe {recipe.name} " + " ".join(f"--arg {m}=…" for m in missing), file=sys.stderr)
            return 1

        if verbose:
            print(f"{recipe.name}: {recipe.description or 'a recorded routine'}")
            for number, step in enumerate(self._recipe_lines(recipe, arguments), 1):
                print(f"  {number}. {step}")
            if dry_run:
                print("dry run: these steps are not being performed")

        config = self.config
        if dry_run:
            config = config.merged(**{"safety.dry_run": True})
        bridge = AgentBridge(config)
        self.bridge = bridge
        bridge.start()
        try:
            result = bridge.run_recipe(recipe, arguments)
            print(result)
            return 0 if not result.startswith("I could not") else 1
        finally:
            bridge.stop()

    @staticmethod
    def _recipe_lines(recipe: Any, arguments: Dict[str, str]) -> List[str]:
        """A routine's steps as sentences, for `--dry-run` and the panel log.

        Worth printing even when the run is real: a routine replays faithfully,
        which is exactly why the user should see what it is about to do before it
        does it.
        """
        from .skills.base import render_recipe

        lines: List[str] = []
        for payload in render_recipe(recipe, arguments or {}):
            kind = str(payload.get("type", "?"))
            detail = ""
            if kind in ("click", "double_click", "right_click", "move"):
                detail = f"at {payload.get('x')},{payload.get('y')}"
            elif kind in ("type", "paste"):
                detail = repr(str(payload.get("text", ""))[:60])
            elif kind in ("key", "hotkey"):
                keys = payload.get("keys") or payload.get("key") or payload.get("hotkey") or ""
                modifiers = payload.get("modifiers") or []
                if isinstance(modifiers, str):
                    modifiers = [modifiers]
                detail = "+".join([str(item) for item in modifiers] + [str(keys)]) if modifiers else str(keys)
            elif kind == "edit_field":
                place = payload.get("target") or f"{payload.get('x')},{payload.get('y')}"
                value = payload.get("value") or payload.get("text") or ""
                if not value and (payload.get("old") or payload.get("new")):
                    value = f"{payload.get('old', '')} → {payload.get('new', '')}"
                detail = f"{payload.get('operation', 'set')} {place}"
                if value:
                    detail += f" to {str(value)[:60]!r}"
            elif kind == "skill_tool":
                detail = f"{payload.get('tool')}({payload.get('args') or {}})"
            elif kind == "wait":
                detail = f"{payload.get('seconds', 1)}s"
            note = payload.get("note") or ""
            lines.append(" ".join(part for part in (kind, detail, f"— {note}" if note else "") if part).strip())
        return lines

    def teach(
        self,
        name: str,
        *,
        description: str = "",
        variables: Optional[Dict[str, str]] = None,
        seconds: float = 0.0,
        verbose: bool = True,
    ) -> int:
        """Learn a routine by watching the user perform it once."""
        from .control.editing import looks_like_field_label
        from .skills.base import SkillStore
        from .skills.recorder import ActionRecorder, Tailer, distill_recipe, suggest_parameters

        store = SkillStore(self.config).load()
        watcher = None
        capture = None
        try:
            from .agent.bridge import AgentBridge

            bridge = AgentBridge(self.config)
            watcher = bridge.watcher
            capture = bridge.capture
        except Exception as error:
            logger.debug("teaching without a watcher: %s", error)

        def screenshot() -> Optional[str]:
            if capture is None:
                return None
            try:
                frame = capture.grab()
                if watcher is not None:
                    return str(watcher.snapshot(fresh=True, save=True).saved_path or "")
                return str(getattr(frame, "saved_path", "") or "")
            except Exception:
                return None

        def ocr_label(path: str, x: int, y: int) -> str:
            """The visible text nearest a click point — the step's anchor.

            A recorded coordinate is only valid while the window stays where it
            was. The label Naveed saw under the click is what lets replay find
            that element again after the window has moved, so it is worth an OCR
            pass per click (and the whole feature works without OCR, it just
            records coordinates instead of labels).
            """
            try:
                from .control.ocr import read_text

                Image = lazy.load("PIL.Image", extra="capture")
                with Image.open(path) as handle:
                    matches = read_text(handle.convert("RGB"))
            except Exception:
                return ""
            best = None
            best_distance = None
            for match in matches:
                centre_x = (match.left + match.right) / 2.0
                centre_y = (match.top + match.bottom) / 2.0
                # Prefer text close to the click, and prefer a label-like string
                # ("Description", "Status") over a sentence.
                distance = ((centre_x - x) ** 2 + (centre_y - y) ** 2) ** 0.5
                if distance > 220:
                    continue
                if not looks_like_field_label(match.text) and distance > 60:
                    continue
                if best_distance is None or distance < best_distance:
                    best, best_distance = match.text.strip(), distance
            return best or ""

        def window() -> Any:
            try:
                from .screen.focus import active_window

                return active_window()
            except Exception:
                return None

        recorder = ActionRecorder(name, window=window, screenshot=screenshot, ocr=ocr_label)
        recorder.start()
        tailer = Tailer(recorder)
        if not tailer.available():
            print(
                "recording needs the input extra (pynput):\n"
                '  pip install "naveed[input]"',
                file=sys.stderr,
            )
            return 1
        if not tailer.start():
            print("could not hook the mouse and keyboard on this system", file=sys.stderr)
            return 1

        print(f"Recording “{name}”. Do the task once, the way you normally would.")
        print("  · Naveed is only watching: it will not act while you demonstrate.")
        print("  · Press Ctrl+Alt+T or Ctrl-C when you are finished.")
        if seconds:
            print(f"  · recording for up to {seconds:.0f} seconds")
        try:
            started = time.time()
            while True:
                if seconds and time.time() - started >= seconds:
                    break
                if self._teach_stop_requested():
                    break
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\n(stopped by Ctrl-C)")
        finally:
            tailer.stop()

        session = recorder.stop()
        print(f"\n{session.summary()}")

        typed_values = []
        for event in session.events:
            if event.kind == "text" and event.text.strip():
                typed_values.append(event.text)
        suggestions = suggest_parameters(typed_values) if not variables else {}
        if suggestions:
            print("\nValues you typed that look like they change per run:")
            for text, parameter in suggestions.items():
                print(f"    {text!r}  ->  {{{{{parameter}}}}}")
            print("  (pass --var 'PROJ-1042=work_item_id' to rename one; --var 'text=' drops it)")

        recipe = distill_recipe(
            session,
            description=description or f"recorded on {time.strftime('%Y-%m-%d')}",
            variables=variables or suggestions,
        )
        if not recipe.steps:
            print("nothing usable was recorded — try again and use the mouse for at least one click", file=sys.stderr)
            return 1
        path = store.save_recipe(recipe)
        print(f"\nLearned “{recipe.name}”: {len(recipe.steps)} steps, {len(recipe.params)} parameter(s).")
        for index, step in enumerate(recipe.steps, 1):
            detail = step.params.get("text") or step.params.get("hotkey") or step.params.get("key") or step.anchor or ""
            print(f"  {index}. {step.kind} {detail}")
        print(f"\nSaved to {path}")
        print(f"Run it again with:\n  python -m naveed --run-recipe {recipe.name}" + "".join(f" --arg {name}=…" for name in recipe.params))
        return 0

    def _teach_stop_requested(self) -> bool:
        """True once the stop hotkey has been pressed (the overlay sets the flag)."""
        return bool(getattr(self, "_teach_stop", False))

    def export_training(self, path: str, *, verbose: bool = True) -> int:
        """Write recorded steps as JSONL for later fine-tuning of a small model.

        Naveed cannot fine-tune anything on your desktop — but it can record what
        actually happened (the task, the screen state, the action, whether the
        action changed the screen) in the shape a training run wants. This is the
        bridge between "demonstrate it to me" and "train a model on it".
        """
        import json
        from .skills.base import SkillStore

        store = SkillStore(self.config).load()
        rows: List[Dict[str, Any]] = []
        for recipe in store.all_recipes():
            for index, step in enumerate(recipe.steps):
                rows.append(
                    {
                        "kind": "demonstration",
                        "routine": recipe.name,
                        "app": recipe.app,
                        "step": index + 1,
                        "action": {"type": step.kind, **step.params},
                        "anchor": step.anchor,
                        "window": step.window,
                    }
                )
        for task in getattr(self, "recent_tasks", []) or []:
            for step in getattr(task, "steps", []) or []:
                rows.append({"kind": "task", "task": getattr(task, "prompt", ""), "step": step})

        if not rows:
            print("nothing recorded yet — use --teach to demonstrate a task first", file=sys.stderr)
            return 1
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"wrote {len(rows)} example(s) to {path}")
        if verbose:
            print("  · fine-tuning is not something a desktop app does on your machine;")
            print("    this is the dataset to take to a training run if you want one.")
        return 0

    def run_watch(self, *, seconds: float = 0.0, verbose: bool = True) -> int:
        """Headless screen watching: print what the world model sees."""
        from .agent.bridge import AgentBridge

        bridge = AgentBridge(self.config)
        self.bridge = bridge
        if verbose:
            print("Watching the screen. Ctrl-C to stop.")
        bridge.start()
        started = time.time()
        seen = 0
        try:
            while True:
                state = bridge.watcher.latest
                if state is not None and seen != len(bridge.watcher.graph.history):
                    seen = len(bridge.watcher.graph.history)
                    if verbose:
                        print(f"  {state.to_prompt_line()}")
                if seconds and time.time() - started > seconds:
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            print()
        finally:
            if verbose:
                print(bridge.watcher.world_summary(lines=8))
                print(bridge.watcher.stats_payload()["watcher"])
            bridge.stop()
        return 0

    def listen_once(self, *, seconds: float = 12.0) -> int:
        """Record one spoken command and print the transcript."""
        from .speech import VoiceLoop

        loop = VoiceLoop(self.config)
        if not loop.can_listen:
            print("no microphone is available (install the 'voice' extra: sounddevice)", file=sys.stderr)
            return 2
        print("listening…")
        loop.listener.microphone.max_seconds = seconds
        text = loop.listen_blocking()
        loop.close()
        if not text:
            print("(nothing recognised)")
            return 1
        print(text)
        return 0

    def say(self, text: str) -> int:
        """Speak *text* through the configured offline voice."""
        from .speech import Speaker, available_engines

        speaker = Speaker(self.config.voice)
        result = speaker.speak_now(text)
        if not result.ok:
            print(result.message, file=sys.stderr)
            print(f"available engines: {', '.join(available_engines()) or 'none'}", file=sys.stderr)
            return 2
        print(f"spoken with {result.engine}")
        return 0

    def screenshot(self) -> int:
        """Take one screenshot and report the path."""
        from .screen.capture import CaptureError
        from .screen.retention import ScreenshotStore
        from .screen.watch import ScreenWatcher

        store = ScreenshotStore(str(self.config.screenshots_dir), max_captures=self.config.capture.max_captures)
        watcher = ScreenWatcher(store=store, save_frames=True, target=self.config.capture.target)
        try:
            frame = watcher.snapshot(fresh=True, save=True)
        except CaptureError as error:
            print(str(error), file=sys.stderr)
            return 2
        path = frame.saved_path or "(not saved)"
        print(f"{path}\n{frame.width}x{frame.height} via {frame.via} on monitor {frame.monitor.index}")
        return 0

    # --- setup ---------------------------------------------------------------
    def setup(self, *, provider: str = "", model: str = "", api_key: str = "", voice: str = "", force: bool = False) -> int:
        """Write a working ``config.env`` (and optionally fetch a voice model)."""
        config = self.config
        if provider:
            preset = PROVIDER_PRESETS.get(provider)
            if preset is None:
                print(f"unknown provider {provider!r}; choose from {', '.join(sorted(PROVIDER_PRESETS))}", file=sys.stderr)
                return 2
            config.llm.base_url = preset["base_url"]
            config.llm.model = model or preset["model"]
        if model:
            config.llm.model = model
        if api_key:
            config.llm.api_key = api_key

        target = os.path.join(str(config.base_dir), "config.env")
        if os.path.exists(target) and not force:
            print(f"{target} already exists — pass --force to overwrite", file=sys.stderr)
            return 1
        path = write_env_file(config, target)
        os.makedirs(str(config.screenshots_dir), exist_ok=True)
        print(f"wrote {path}")
        print(f"  screenshots: {config.screenshots_dir}")
        print(f"  model:       {config.llm.label}")

        if voice:
            from .speech import download_voice

            try:
                model_path = download_voice(voice, directory=os.path.join(str(config.base_dir), "models", "piper"), progress=print)
                print(f"  voice model: {model_path}")
                config.voice.piper_voice = model_path
                write_env_file(config, target)
            except Exception as error:
                print(f"could not download the voice: {error}", file=sys.stderr)
                print("  (the built-in OS voice will be used instead)", file=sys.stderr)
        return 0


# --- helpers ----------------------------------------------------------------

def describe_environment(config: Config) -> Dict[str, Any]:
    """Collect everything the status report needs, never raising."""
    from .screen.capture import available_backends
    from .screen.capture_fallback import get_screen_access_status

    capture_backends: List[str] = []
    try:
        capture_backends = [backend.name for backend in available_backends()]
    except Exception:
        capture_backends = []

    input_backends: List[str] = []
    try:
        from .control.input import available_backends as input_backends_fn

        input_backends = [backend.name for backend in input_backends_fn()]
    except Exception:
        input_backends = []

    ocr: List[str] = []
    try:
        from .control.ocr import ocr_backends

        ocr = ocr_backends()
    except Exception:
        ocr = []

    speech = {"microphone": False, "transcribers": [], "tts_engines": []}
    try:
        from .speech import summary as speech_summary

        speech = speech_summary()
    except Exception:
        pass

    required = []
    if lazy.find_spec_safe("PySide6") is None:
        required.append("PySide6 (ui)")
    if not capture_backends:
        required.append("capture backend (mss/Pillow)")

    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "home": str(config.base_dir),
        "config_file": config.source_file,
        "model": config.llm.label,
        "model_ready": config.llm.configured,
        "ui": lazy.find_spec_safe("PySide6") is not None,
        "capture_backends": capture_backends,
        "screen_access": get_screen_access_status(),
        "input_backends": input_backends,
        "ocr": ocr,
        "speech": speech,
        "missing_required": required,
    }


def install_hint_text() -> str:
    """The one line a user needs when something required is missing."""
    return (
        "Install what is missing, then run Naveed again:\n"
        '  pip install "naveed[ui,capture,input]"\n'
        "  python -m naveed --setup --provider ollama   # or openai / openrouter / groq\n"
        "  python -m naveed --check"
    )


def _echo(enabled: bool, line: str) -> None:
    if enabled:
        print(line, flush=True)
