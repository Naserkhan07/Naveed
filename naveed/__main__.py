"""Command line entry point: ``python -m naveed``.

Modes
-----
``python -m naveed``                      start the floating companion
``python -m naveed --prompt "open X"``    run one task headlessly
``python -m naveed --watch``              watch the screen, print a timeline
``python -m naveed --check``              report what is installed/possible
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
from typing import List, Optional

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
    parser.add_argument("--setup", action="store_true", help="write a config file (see --provider/--api-key)")
    parser.add_argument("--portrait", nargs="?", const="naveed-portrait.png", metavar="PATH", help="render the mascot sheet + panel mock to a PNG")
    parser.add_argument("--listen", nargs="?", const=12.0, type=float, metavar="SECONDS", help="record one voice command and print the text")
    parser.add_argument("--say", metavar="TEXT", help="speak TEXT with the offline voice")
    parser.add_argument("--screenshot", action="store_true", help="take one screenshot and print the path")

    parser.add_argument("--provider", metavar="NAME", help=f"setup preset ({', '.join(sorted(_presets()))})")
    parser.add_argument("--model", metavar="NAME", help="model name for the planner")
    parser.add_argument("--api-key", metavar="KEY", help="API key (stored in ~/.naveed/config.env)")
    parser.add_argument("--voice", nargs="?", const="en_US-amy-medium", metavar="NAME", help="download a Piper voice during setup")

    parser.add_argument("--base-url", metavar="URL", help="OpenAI-compatible endpoint")
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
    if args.api_key:
        overrides["llm.api_key"] = args.api_key
    if args.size:
        overrides["overlay.size"] = args.size
    if args.interval is not None:
        overrides["capture.interval"] = args.interval
    if args.dry_run:
        overrides["safety.dry_run"] = True
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
            api_key=args.api_key or "",
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
    if args.prompt:
        return app.run_task(args.prompt)
    return app.run_overlay()


if __name__ == "__main__":
    sys.exit(main())
