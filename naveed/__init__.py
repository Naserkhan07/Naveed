"""Naveed — a floating desktop AI companion.

The mascot floats above every window, watches the screen, and does the task it is
asked to do *on that screen*: clicking, typing, scrolling and reporting back with a
voice.  That is the surface Naveed is built around — not a website, not a terminal
UI.

The same bot is also served to a browser (:mod:`naveed.server`, ``python -m naveed
--serve``) for when a text box and a scrollback are handier, and for machines with
no Qt at all.  It is a *second window onto one bot*, not a different product: both
front ends drive the same agent, and neither is required for the other to work.

This package is deliberately import-cheap: see :mod:`naveed.lazy` for the rule that
every heavy dependency is loaded at first use instead of at start-up.
"""

from __future__ import annotations

from typing import Any, Dict

from .lazy import MissingDependencyError, load, optional, report  # noqa: F401

__version__ = "0.2.0"
__all__ = ["__version__", "MissingDependencyError", "load", "optional", "report"]

_LAZY_SUBMODULES: Dict[str, str] = {
    "config": "naveed.config",
    "app": "naveed.app",
    "server": "naveed.server",
    "webui": "naveed.webui",
    "skills": "naveed.skills",
    "screen": "naveed.screen",
    "overlay": "naveed.overlay",
    "agent": "naveed.agent",
    "control": "naveed.control",
    "speech": "naveed.speech",
    "lazy": "naveed.lazy",
    "logging_setup": "naveed.logging_setup",
}


def __getattr__(name: str) -> Any:
    """Import sub-packages only when someone actually touches them."""
    target = _LAZY_SUBMODULES.get(name)
    if target is None:
        raise AttributeError(f"module 'naveed' has no attribute {name!r}")
    return load(target)


def __dir__() -> list:
    return sorted(set(__all__) | set(_LAZY_SUBMODULES))
