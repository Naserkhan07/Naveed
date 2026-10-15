"""Logging configuration.

Naveed logs to ``~/.naveed/logs/naveed.log`` (rotating) and, when asked, to the
console.  A desktop companion must never spam a terminal the user is not looking
at, and must never print a traceback on top of their work — so the default level
is WARNING on the console and INFO in the file.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

__all__ = ["setup_logging", "LOG_FORMAT"]

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
MAX_BYTES = 1_000_000
BACKUPS = 3


def setup_logging(
    *,
    level: str = "INFO",
    console: bool = False,
    directory: Optional[str] = None,
    quiet_libraries: bool = True,
) -> str:
    """Configure logging and return the log file path (empty when not used)."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT)
    log_path = ""
    target_dir = directory or os.path.join(os.path.expanduser("~"), ".naveed", "logs")
    try:
        os.makedirs(target_dir, exist_ok=True)
        log_path = os.path.join(target_dir, "naveed.log")
        handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        log_path = ""

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.setLevel(getattr(logging, level.upper(), logging.INFO))
        root.addHandler(stream)

    if quiet_libraries:
        for name in ("PIL", "mss", "urllib3", "asyncio", "PySide6"):
            logging.getLogger(name).setLevel(logging.WARNING)

    return log_path


def recent_log_lines(count: int = 80, *, directory: Optional[str] = None) -> list:
    """Last lines of the log file (the panel's diagnostics sheet uses this)."""
    target = Path(directory or os.path.join(os.path.expanduser("~"), ".naveed", "logs")) / "naveed.log"
    if not target.exists():
        return []
    try:
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()[-count:]
    except OSError:
        return []
