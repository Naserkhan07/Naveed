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
                print("no task ran", file=sys.stderr)
                return 1
            print(f"\n{task.status.value.upper()}: {task.result}")
            for step in task.steps:
                marker = "✔" if step.get("ok") else "✕"
                print(f"  {step.get('step')}. {marker} {step.get('description', '')} — {step.get('message', '')}")
            return 0 if task.status.value == "done" else 1
        finally:
            bridge.stop()

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
