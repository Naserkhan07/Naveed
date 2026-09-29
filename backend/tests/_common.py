"""Shared helpers for the calibration scripts (all run headless + offline: no network, no LLM)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SOUL_OFFLINE", "1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from soul_exter.engine.floor import FloorEngine  # noqa: E402


def run_engine(sim_seconds: float, seed: int = 7, speed: float = 32.0, ceo_doctrine: bool = False) -> FloorEngine:
    """Run the whole floor headless for `sim_seconds` of simulated time."""
    eng = FloorEngine(seed=seed)
    eng.set_settings({"speed": speed, "live": False, "ceo_doctrine": ceo_doctrine, "ambient": 4})
    eng.router.force_offline = True
    dt = 0.05
    while eng.sim_t < sim_seconds:
        eng.step(dt)
    return eng


def arg(i: int, default: float) -> float:
    try:
        return float(sys.argv[i])
    except (IndexError, ValueError):
        return default


def table(rows: list[list], head: list[str]) -> str:
    w = [max(len(str(x)) for x in col) for col in zip(head, *rows)] if rows else [len(h) for h in head]
    fmt = "  ".join(f"{{:>{k}}}" for k in w)
    return "\n".join([fmt.format(*head), fmt.format(*["-" * k for k in w])] + [fmt.format(*[str(x) for x in r]) for r in rows])


def resolved(eng: FloorEngine):
    return [t for t in eng.tickets.values() if t.r is not None]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")
