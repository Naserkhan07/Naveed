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
4. starts the bot: the mascot appears centred just below the camera and can be
   clicked to open the panel and talk, and the same bot is also served to your
   browser (``http://127.0.0.1:8765``) so you can type to it from a real text box.

If PySide6 is not installed there is no floating mascot, but that is not a reason
to leave you with nothing: the browser half needs only the standard library, so
the bot comes up there instead.

Run it with Python:

    python main.py                 # start the bot (mascot + browser)
    python main.py --check         # report what is installed, then exit
    python main.py --serve         # the same bot in a browser only, no window
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
            print("  without PySide6 I will still come up in your browser — no window needed.", file=stream)
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
    """Bring the bot up, with the mascot when there is Qt and a browser either way.

    The browser half is normally started *by the overlay* (it hands over its own
    bridge, so both front ends drive one bot). The interesting case is the machine
    with no PySide6 — or one where Qt cannot open a window at all, which happens in
    containers that have no ``libGL.so.1``. Instead of printing an install hint and
    exiting, the bot comes up in the browser, because that half needs nothing but
    the standard library.
    """
    stream = stream or sys.stdout
    try:
        from naveed import lazy
    except ImportError:  # pragma: no cover - naveed itself is missing
        return 1

    if lazy.find_spec_safe("PySide6") is None:
        print("No PySide6, so there is no floating mascot on this machine.", file=stream)
        print('  install it with: pip install "naveed[ui]"', file=stream)
        print("  until then, the same bot is in your browser — opening it now:", file=stream)
        print()
        return app.run_server(open_browser=True)

    code = app.run_overlay(serve=bool(getattr(config.web, "enabled", True)), open_browser=False)
    if code == 2 and getattr(config.web, "enabled", True):
        # Qt is installed but could not open a window (a missing libGL, most
        # often). Talk to the bot in the browser rather than to nothing.
        print("The window could not open, so the bot is coming up in your browser instead:", file=stream)
        print()
        return app.run_server(open_browser=True)
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(130)
