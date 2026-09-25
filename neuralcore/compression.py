"""CAPABILITY PER BYTE — the reframed goal, as a measurement.

Not "does the file contain readable sentences?" (it never did) but:

    140 KB -> how much learned capability does it retain,
              and how much can we compress it before capability breaks?

Two axes are measured:

  SIZE AXIS   — train the same curriculum in brains of different capacity
                and find the minimal brain that still holds the knowledge.
  PRUNE AXIS  — take one trained brain and compress it post-hoc (global
                magnitude pruning), measuring capability at each sparsity.

Together they give the compression frontier: the smallest persistent state
that retains capability — with zero external memory, as always.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import replace

import numpy as np

from . import metrics
from .brain import Brain, BrainConfig
from .experiments import LEARNING_RATE, MODES

# Capacity presets for the size axis (dim, hidden, sparsity_k).
SIZE_PRESETS: dict[str, tuple[int, int, int]] = {
    "nano": (48, 96, 16),
    "compressed": (64, 128, 24),
    "mid": (96, 192, 32),
    "full": (256, 512, 48),
}


# -- the capability metric ----------------------------------------------------

def capability_score(brain, sets=None) -> float:
    """One number for 'how much capability survives': retention over the
    trained blocks + never-trained paraphrase + never-trained composition."""
    names = sets or ["A", "B", "C", "D"]
    ret = float(np.mean(list(metrics.evaluate_all(brain, set_names=names).values())))
    para, _ = metrics.evaluate_paraphrase(brain)
    comp, _ = metrics.evaluate_composition(brain)
    return 0.5 * ret + 0.25 * para + 0.25 * comp


# -- the prune axis ------------------------------------------------------------

def magnitude_prune(brain: Brain, frac: float) -> int:
    """Global magnitude pruning in place: zero the smallest |frac| of all
    weights (biases included). Returns the number of synapses removed."""
    if frac <= 0:
        return 0
    params = brain.net.named_parameters()
    mags = np.concatenate([np.abs(p).ravel() for p in params.values()])
    threshold = float(np.quantile(mags, frac))
    pruned = 0
    for p in params.values():
        dead = np.abs(p) < threshold
        pruned += int(np.count_nonzero(dead & (p != 0.0)))
        p[dead] = 0.0
    return pruned


def compression_curve(brain: Brain, fracs=(0.0, 0.2, 0.4, 0.6, 0.7, 0.8, 0.9)) -> list[dict]:
    """Capability of one trained brain at increasing post-hoc compression."""
    work = copy.deepcopy(brain)
    curve = []
    for frac in fracs:
        pruned = magnitude_prune(work, frac)
        curve.append(
            {
                "pruned_frac": frac,
                "synapses_pruned": pruned,
                "live_weights": work.net.nonzero_parameter_count(),
                "brain_bytes": work.byte_size(),
                "capability": capability_score(work),
            }
        )
    return curve


def minimal_viable(curve: list[dict], relative: float = 0.95) -> dict:
    """Smallest state on the curve that keeps `relative` of uncompressed capability."""
    cap0 = curve[0]["capability"]
    target = relative * cap0
    viable = [row for row in curve if row["capability"] >= target]
    if not viable:
        return {"reachable": False, "target_capability": target}
    best = min(viable, key=lambda r: r["brain_bytes"])
    return {
        "reachable": True,
        "target_capability": target,
        "pruned_frac": best["pruned_frac"],
        "brain_bytes": best["brain_bytes"],
        "capability": best["capability"],
        "compression_ratio": curve[0]["brain_bytes"] / max(1, best["brain_bytes"]),
    }


# -- the size axis ---------------------------------------------------------------

def config_for(size: str, mode: str = "consolidation", seed: int = 0) -> BrainConfig:
    dim, hidden, k = SIZE_PRESETS[size]
    return BrainConfig(dim=dim, hidden=hidden, sparsity_k=k, gate_lambda=MODES.get(mode, 15.0), seed=seed)


def size_axis(mode: str = "consolidation", epochs: int = 24, seed: int = 0, log=None) -> list[dict]:
    """Same curriculum, different brain capacities: capability vs size."""
    from .curriculum import Curriculum

    log = log or (lambda *a, **k: None)
    rows = []
    set_names = Curriculum().set_names()
    for size in SIZE_PRESETS:
        from .experiments import train_brain

        brain, _ = train_brain(mode=mode, config=config_for(size, mode, seed), sets=set_names,
                               epochs_per_set=epochs, log=None)
        row = {
            "size": size,
            "config": SIZE_PRESETS[size],
            "parameters": brain.net.parameter_count(),
            "brain_bytes": brain.byte_size(),
            "capability": capability_score(brain),
        }
        rows.append(row)
        log(
            f"  {size:<12} {row['parameters']:>7,} params  {row['brain_bytes']:>9,} B  "
            f"capability {row['capability']:.2f}"
        )
    return rows


# -- the experiment ------------------------------------------------------------

def run(out_dir: str = "neuralcore_output", mode: str = "consolidation", seed: int = 0, log=print) -> dict:
    from .experiments import train_brain

    log("CAPABILITY PER BYTE — the compression frontier")
    log("\n[1] size axis: same curriculum, shrinking brains")
    rows = size_axis(mode=mode, seed=seed, log=log)

    log("\n[2] prune axis: post-hoc compression of the trained 'compressed' brain")
    brain, _ = train_brain(mode=mode, config=config_for("compressed", mode, seed), log=None)
    cap0 = capability_score(brain)
    log(f"    uncompressed: {brain.byte_size():,} B, capability {cap0:.2f}")
    curve = compression_curve(brain)
    for row in curve:
        log(
            f"    prune {row['pruned_frac']:.0%}: {row['live_weights']:>6,} live weights, "
            f"{row['brain_bytes']:>8,} B, capability {row['capability']:.2f}"
        )

    mv = minimal_viable(curve)
    size_best = min((r for r in rows if r["capability"] >= 0.95 * rows[-1]["capability"]),
                    key=lambda r: r["parameters"], default=None)

    report = {
        "mode": mode,
        "capability_definition": "0.5*retention + 0.25*paraphrase + 0.25*composition",
        "size_axis": rows,
        "prune_curve": curve,
        "minimal_viable_prune": mv,
        "minimal_viable_size": size_best,
        "external_memory_bytes": 0,
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "compression-report.json"), "w") as f:
        json.dump(report, f, indent=2)

    log("\nfrontier:")
    if size_best:
        log(
            f"  smallest brain holding capability: {size_best['size']} "
            f"({size_best['parameters']:,} params, {size_best['brain_bytes']:,} B)"
        )
    if mv.get("reachable"):
        log(
            f"  deepest safe pruning: {mv['pruned_frac']:.0%} of synapses removed -> "
            f"{mv['brain_bytes']:,} B ({mv['compression_ratio']:.1f}x), "
            f"capability {mv['capability']:.2f} (target {mv['target_capability']:.2f})"
        )
    log(f"  external memory: 0 bytes, as always")
    return report


if __name__ == "__main__":
    run()
