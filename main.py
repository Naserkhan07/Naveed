#!/usr/bin/env python3
"""Start Naveed: the floating bot.

This is the entry point to double-click. It does the four things a person expects
from "run the bot":

1. finds Naveed (next to this file, or installed), and says so if it cannot;
2. makes sure there is a config, offering the sensible defaults for whatever LLM
   API it can see on this machine (a local Ollama or LM Studio that answers, or an
   endpoint already in the environment);
3. tells you the truth about the LLM API *before* the bot appears — a configured
   address that nothing is answering on is the single most confusing failure, so
   it is reported here rather than after a task dies;
4. starts the bot: the mascot appears centred just below the camera, and clicking
   it opens the panel and the task box.

**This is a desktop window, and only a desktop window.** If PySide6 — or one of
the system libraries Qt links against — is missing, main.py says exactly what is
missing and how to install it instead of quietly turning into something else. The
optional HTTP front end is a separate command (``python main.py --serve``).

Run it with Python:

    python main.py                 # start the bot: the floating window
    python main.py --overlay-check # does the window come up? and why not
    python main.py --check         # report what is installed, then exit
    python main.py --serve         # optional: the same bot over HTTP, no window
    python main.py -p "..."        # headless one-shot task

Everything after ``--`` is passed straight to Naveed, so every documented flag
(``--teach``, ``--run-recipe``, ``--skills``, ``--dry-run`` …) works here too.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent


def _make_importable() -> None:
    """Import Naveed from this checkout, or from site-packages if installed."""
    from importlib.util import find_spec

    if find_spec("naveed") is not None:
        return
    if (REPO_ROOT / "naveed" / "__init__.py").exists():
        sys.path.insert(0, str(REPO_ROOT))


def _banner(message: str = "") -> None:
    line = "─" * 6
    print(f"\n{line} Naveed {line}")
    print("  the floating bot · click it to open the panel and tell it what to do")
    if message:
        print(f"  {message}")
    print()


def _first_run_hints(config, *, stream=None) -> None:
    """Say what is missing *before* the window opens, in one short block."""
    stream = stream or sys.stdout
    try:
        from naveed import lazy
    except ImportError:  # pragma: no cover - only if naveed itself is missing
        return

    missing = []
    if lazy.find_spec_safe("PySide6") is None:
        missing.append(('no PySide6 — there is no window without it', 'pip install "naveed[ui,capture,input]"'))
    if lazy.find_spec_safe("mss") is None and lazy.find_spec_safe("PIL") is None:
        missing.append(("no screen-capture backend — I cannot see the screen", 'pip install "naveed[capture]"'))
    if lazy.find_spec_safe("pynput") is None:
        missing.append(("no input backend — I cannot move the mouse or type", 'pip install "naveed[input]"'))

    if missing:
        print("Before I can work, I need:", file=stream)
        for what, how in missing:
            print(f"  • {what}\n      {how}", file=stream)
        print('  (one command does all three: pip install "naveed[ui,capture,input]")', file=stream)
        if any(what.startswith("no PySide6") for what, _ in missing):
            print("  without PySide6 there is no floating window — see python main.py --overlay-check", file=stream)
        print()

    if not config.source_file or not config.llm.configured:
        print("I do my thinking with an LLM *API* (a URL and a model — no keys involved).", file=stream)
        print(f"  I am using:  {config.llm.base_url}   ({config.llm.model})", file=stream)
        print("  point me at a different one with:", file=stream)
        print("    python main.py --setup --provider ollama     # local, free, nothing leaves your PC", file=stream)
        print("    python main.py --setup --provider lmstudio   # local server with a GUI", file=stream)
        print("    python main.py --api http://127.0.0.1:1234/v1 --model qwen2.5-vl-7b-instruct", file=stream)
        print()


def _default_setup_if_possible(config, *, stream=None) -> None:
    """Write a first config when an LLM API is obviously available.

    Naveed is configured with an *API*, never with a key, so there are exactly two
    cases worth doing without being asked: an endpoint handed to us in the
    environment (``LLM_API``), and a local server that is already *answering* on its
    usual port (Ollama 11434, LM Studio 1234). Anything else is left to ``--setup``:
    guessing an endpoint that refuses connections is the exact confusion this
    function exists to avoid.
    """
    stream = stream or sys.stdout
    if config.source_file:
        return  # an existing config is the user's, and is never rewritten here

    from naveed.agent.llm import LLMClient
    from naveed.config import PROVIDER_PRESETS, Config, write_env_file

    endpoint = os.environ.get("LLM_API") or os.environ.get("NAVEED_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or ""
    model = os.environ.get("LLM_MODEL") or os.environ.get("NAVEED_MODEL") or ""

    chosen: Optional[Tuple[str, str, str]] = None
    if endpoint:
        chosen = ("from your environment", endpoint, model or "gpt-4o-mini")
    else:
        for name in ("ollama", "lmstudio"):
            preset = PROVIDER_PRESETS[name]
            candidate = Config(home=config.home)
            candidate.llm.base_url = preset["base_url"]
            candidate.llm.model = preset["model"]
            reachable, _ = LLMClient(candidate.llm).probe(timeout=1.2)
            if reachable:
                chosen = (name, preset["base_url"], preset["model"])
                break
    if chosen is None:
        return

    name, base_url, model_name = chosen
    fresh = Config(home=config.home)     # write where *this* config was loaded from
    fresh.llm.base_url = base_url
    fresh.llm.model = model_name
    path = write_env_file(fresh)
    if path:
        print(f"I wrote a starting config for you: {path}  (LLM API: {name})", file=stream)
        print()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _make_importable()

    try:
        from naveed.app import NaveedApp
        from naveed.config import load_config
    except ImportError as error:
        print("I could not find the Naveed package next to this file.", file=sys.stderr)
        print(f"  ({error})", file=sys.stderr)
        print("Run me from the repository root, or install it:", file=sys.stderr)
        print('  pip install -e ".[ui,capture,input]"', file=sys.stderr)
        return 1

    # `main.py -- ...` and plain flags both work: everything is just Naveed's CLI.
    if argv and argv[0] == "--":
        argv = argv[1:]

    verbose = bool(argv)
    if not verbose:
        _banner()

    config = load_config()
    if not verbose:
        _default_setup_if_possible(config)
        config = load_config()
        _first_run_hints(config)
        if not config.llm.configured:
            # Still start: the mascot can be seen, dragged and configured from the
            # panel. Refusing to open would be the least useful thing to do.
            print("Starting anyway — the panel's gear icon is where you add a model.\n")

    app = NaveedApp(config)
    if not argv:
        return _start_everything(app, config, stream=sys.stdout)

    # Everything else is the normal command line, so `main.py -p "..."`,
    # `main.py --check` and `main.py --teach name` behave exactly as documented.
    from naveed.__main__ import main as cli_main

    return cli_main(argv)


def _start_everything(app, config, *, stream=None) -> int:
    """Bring the bot up: the floating window, or the reason it cannot appear.

    There is deliberately no fallback to the HTTP front end here. A desktop
    companion that silently becomes a web page on the machines where Qt cannot
    start is the single most confusing thing this program could do — it looks
    exactly like "the bot did not appear", and it was true for anyone whose Qt
    needed a system library that was not installed. So: check first, name the
    problem, and only start a window that can actually be on screen.
    """
    stream = stream or sys.stdout
    try:
        from naveed.overlay.doctor import library_hint, qt_available
    except ImportError:  # pragma: no cover - naveed itself is missing
        return 1

    usable, detail = qt_available()
    if not usable:
        print("Naveed could not open its window on this machine.", file=stream)
        print(file=stream)
        for line in str(detail).splitlines():
            print(f"  {line}", file=stream)
        print(file=stream)
        print('Install the window: pip install "naveed[ui]"', file=stream)
        hint = library_hint(str(detail))
        if hint:
            print("…and the system library Qt needs (that one is not a pip package):", file=stream)
            for line in hint.splitlines():
                if line.strip():
                    print(f"  {line.strip()}", file=stream)
        print(file=stream)
        print("Then ask again — it names exactly what is missing:", file=stream)
        print("  python main.py --overlay-check", file=stream)
        print(file=stream)
        print("Prefer a text box? The same bot can run over HTTP instead (optional):", file=stream)
        print("  python main.py --serve", file=stream)
        return 2

    code = app.run_overlay(open_browser=False)
    if code == 2:
        print(file=stream)
        print("The window did not come up. `python main.py --overlay-check` reports", file=stream)
        print("which part failed (the Qt platform plugin, the screen, or the window).", file=stream)
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(130)
