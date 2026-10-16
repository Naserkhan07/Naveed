"""Command line entry point: ``python -m naveed``.

Modes
-----
``python -m naveed``                      start the floating companion
``python -m naveed --overlay-check``      can the window appear here, and why not
``python -m naveed --prompt "open X"``    run one task headlessly
``python -m naveed --watch``              watch the screen, print a timeline
``python -m naveed --check``              report what is installed/possible
``python -m naveed --serve``              the HTTP front end only, no window (optional)
``python -m naveed --train NAME``         learn a task by demonstration (Polarion, or anything else)
``python -m naveed --polarion-check``     is the Polarion API fast path working?
``python -m naveed --setup``              write ~/.naveed/config.env
``python -m naveed --listen``             record one voice command
``python -m naveed --say "text"``         speak through the offline voice
``python -m naveed --screenshot``         take one screenshot
``python -m naveed --portrait out.png``   render the mascot sheet and panel mock
``python -m naveed --version``

The flags exist so every part of Naveed can be exercised without the GUI, which is
how the project is tested and how a headless machine can still use the agent.
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Optional

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="naveed",
        description="Naveed — a floating desktop AI companion that watches your screen and does the task on it.",
    )
    parser.add_argument("--version", action="version", version=f"Naveed {__version__}")
    parser.add_argument("--prompt", "-p", metavar="TEXT", help="run one task and exit (headless)")
    parser.add_argument("--watch", nargs="?", const=0.0, type=float, metavar="SECONDS", help="watch the screen and print what changes")
    parser.add_argument("--check", action="store_true", help="report the environment and capabilities")
    parser.add_argument("--setup", action="store_true", help="write a config file (see --provider/--api)")
    parser.add_argument("--portrait", nargs="?", const="naveed-portrait.png", metavar="PATH", help="render the mascot sheet + panel mock to a PNG")
    parser.add_argument("--listen", nargs="?", const=12.0, type=float, metavar="SECONDS", help="record one voice command and print the text")
    parser.add_argument("--say", metavar="TEXT", help="speak TEXT with the offline voice")
    parser.add_argument("--screenshot", action="store_true", help="take one screenshot and print the path")

    window = parser.add_argument_group("the floating window (the main way to run Naveed)")
    window.add_argument("--overlay-check", action="store_true",
                        help="can the mascot appear here? Qt, the screen, the window — and why not")
    window.add_argument("--save", metavar="PATH",
                        help="with --overlay-check: write what the windows contain to PATH-mascot.png / PATH-panel.png")

    web = parser.add_argument_group("the browser front end (optional, off by default)")
    web.add_argument("--serve", action="store_true", help="run the HTTP front end *instead of* the window (works without PySide6)")
    web.add_argument("--host", metavar="HOST", help="interface to listen on (default 127.0.0.1; 0.0.0.0 needs the printed token)")
    web.add_argument("--port", type=int, metavar="PORT", help="port for the browser front end (default 8765, or the next free one)")
    web.add_argument("--open-browser", action="store_true", help="open the page in your browser once it is up")
    web.add_argument("--no-token", action="store_true", help="do not require the token when listening beyond loopback")

    trained = parser.add_argument_group("taught knowledge (Polarion and friends)")
    trained.add_argument("--skills", action="store_true", help="list the knowledge packs Naveed has been taught")
    trained.add_argument("--recipes", action="store_true", help="list every routine, with its arguments")
    trained.add_argument("--teach", metavar="NAME", help="learn a task by performing it once, then saving it as a routine")
    trained.add_argument("--train", metavar="NAME", help="the same, with a countdown and the pack's own tips before it records")
    trained.add_argument("--countdown", type=float, default=3.0, metavar="SECONDS", help="seconds to switch windows before --train records (default 3)")
    trained.add_argument("--skill", metavar="PACK", help="print what this knowledge pack already knows before recording")
    trained.add_argument("--polarion-check", action="store_true", help="is the Polarion API fast path configured, and is it answering?")
    trained.add_argument("--teach-seconds", type=float, default=0.0, metavar="SECONDS", help="stop recording after this long")
    trained.add_argument("--run-recipe", metavar="NAME", help="replay a recorded routine (no model needed)")
    trained.add_argument("--arg", action="append", default=[], metavar="KEY=VALUE", help="argument for --run-recipe (repeatable)")
    trained.add_argument("--var", action="append", default=[], metavar="TEXT=NAME", help="turn a recorded value into a parameter (repeatable)")
    trained.add_argument("--describe", metavar="TEXT", help="description to store with a taught routine")
    trained.add_argument("--export-training", metavar="PATH", help="write recorded steps as JSONL for a training run")
    trained.add_argument("--no-skills", action="store_true", help="ignore knowledge packs for this run")

    parser.add_argument("--provider", metavar="NAME", help=f"setup preset ({', '.join(sorted(_presets()))})")
    parser.add_argument("--model", metavar="NAME", help="model name for the planner")
    parser.add_argument("--api", metavar="URL", help="the LLM API to use, e.g. http://127.0.0.1:11434/v1")
    parser.add_argument("--token", metavar="TOKEN", help="only if that LLM API asks for one (optional, never required)")
    parser.add_argument("--voice", nargs="?", const="en_US-amy-medium", metavar="NAME", help="download a Piper voice during setup")

    parser.add_argument("--base-url", metavar="URL", help="the LLM API endpoint (same as --api)")
    parser.add_argument("--size", type=int, metavar="PX", help="mascot size in pixels")
    parser.add_argument("--interval", type=float, metavar="SECONDS", help="screen watching interval")
    parser.add_argument("--dry-run", action="store_true", help="plan and show actions without performing them")
    parser.add_argument("--allow-shell", action="store_true", help="allow shell actions (off by default)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing config file")
    parser.add_argument("--debug", action="store_true", help="verbose logging on the console")
    parser.add_argument("--log-level", default="INFO", metavar="LEVEL")
    return parser


def _presets():
    from .config import PROVIDER_PRESETS

    return PROVIDER_PRESETS


def _pairs(items: List[str]) -> Dict[str, str]:
    """Parse repeated ``KEY=VALUE`` / ``TEXT=NAME`` flags.

    ``--arg status=Verified`` and ``--var "PROJ-1042=work_item_id"``. An item with
    no ``=`` is ignored rather than guessed at, and a trailing ``=`` means "drop
    this one" (used by ``--var`` to reject a parameter suggestion).
    """
    parsed: Dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from .logging_setup import setup_logging

    setup_logging(level="DEBUG" if args.debug else args.log_level, console=args.debug or args.check)

    from .app import NaveedApp
    from .config import load_config

    overrides = {}
    if args.base_url:
        overrides["llm.base_url"] = args.base_url
    if args.model:
        overrides["llm.model"] = args.model
    if args.api:
        overrides["llm.base_url"] = args.api
    if args.token:
        overrides["llm.token"] = args.token
    if args.size:
        overrides["overlay.size"] = args.size
    if args.interval is not None:
        overrides["capture.interval"] = args.interval
    if args.dry_run:
        overrides["safety.dry_run"] = True
    if getattr(args, "no_skills", False):
        overrides["skills.inject"] = False
    if getattr(args, "no_token", False):
        overrides["web.token"] = False
    if args.allow_shell:
        overrides["safety.allow_shell"] = True
    if args.debug:
        overrides["debug"] = True

    config = load_config(**overrides)
    app = NaveedApp(config)

    if args.check:
        app.print_report()
        return 0
    if args.setup:
        return app.setup(
            provider=args.provider or "",
            model=args.model or "",
            token=args.token or "",
            voice=args.voice or "",
            force=args.force,
        )
    if args.portrait is not None:
        from .render.preview import render_all

        paths = render_all(args.portrait, config=config)
        for label, path in paths.items():
            print(f"{label}: {path}")
        return 0
    if args.say:
        return app.say(args.say)
    if args.listen is not None:
        return app.listen_once(seconds=float(args.listen))
    if args.screenshot:
        return app.screenshot()
    if args.watch is not None:
        return app.run_watch(seconds=float(args.watch))
    if args.skills:
        return app.show_skills()
    if args.recipes:
        return app.show_recipes()
    if args.polarion_check:
        return app.polarion_check()
    if args.teach or args.train:
        return app.teach(
            args.train or args.teach,
            description=args.describe or "",
            variables=_pairs(args.var),
            seconds=float(args.teach_seconds or 0.0),
            countdown=float(args.countdown or 0.0) if args.train else 0.0,
            skill=args.skill or "",
        )
    if args.overlay_check:
        return app.overlay_check(save=args.save or "")
    if args.run_recipe:
        return app.run_recipe(args.run_recipe, _pairs(args.arg))
    if args.export_training:
        return app.export_training(args.export_training)
    if args.prompt:
        return app.run_task(args.prompt)
    if args.serve:
        return app.run_server(host=args.host, port=args.port, open_browser=args.open_browser)
    # `python -m naveed` is the floating window, full stop. The HTTP front end is
    # a separate, explicit choice (`--serve`): a desktop bot that silently turns
    # into a web page on the machines where Qt cannot start is not the product.
    return app.run_overlay(open_browser=args.open_browser)


if __name__ == "__main__":
    sys.exit(main())
