"""THE EXPERIMENT: sequential experience, no replay, no external memory.

    Learn A -> Learn B -> Learn C -> Learn D
    Can it still use A?  B?  C?  Did it learn D?

Two variants run side by side:
  naive          — raw plasticity (the V11-style baseline; expect forgetting)
  consolidation  — metaplastic scheduler + sleep (this project's mechanism)

After training, each brain is serialized to a single .ncb file. Everything
measured afterwards comes from that file alone: the training data is never
consulted by inference.

Run:
    python -m neuralcore.experiments                     # naive vs consolidation
    python -m neuralcore.experiments --mode consolidation
    python -m neuralcore.experiments --size full         # over-provisioned control
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace

import numpy as np

from . import metrics
from .brain import Brain, BrainConfig
from .consolidation import sleep
from .curriculum import Curriculum

LEARNING_RATE = 0.1
MODES: dict[str, float] = {"naive": 0.0, "consolidation": 15.0}


def train_brain(
    mode: str = "consolidation",
    size: str = "compressed",
    seed: int = 0,
    sets: list[str] | None = None,
    log=None,
    config: BrainConfig | None = None,
    epochs_per_set: int | None = None,
):
    """Live one continual-learning stream. Returns (brain, accuracy_matrix).

    size="compressed" — a small brain under real capacity pressure: this is
        where catastrophic forgetting appears and the scheduler earns its keep
        (and the regime the Phase-7 compression roadmap lives in).
    size="full"       — an over-provisioned brain: capacity alone absorbs
        interference, a useful control that shows forgetting is a resource
        question, not magic.
    """
    log = log or (lambda *a, **k: None)
    if config is None:
        big = size == "full"
        config = BrainConfig(
            seed=seed,
            gate_lambda=MODES.get(mode, 15.0),
            dim=64 if not big else 256,
            hidden=128 if not big else 512,
            sparsity_k=24 if not big else 48,
        )
    brain = Brain.build(config)
    cur = Curriculum(epochs_per_set=epochs_per_set or 24)
    set_names = sets or cur.set_names()

    # training runs through THE LOOP (stages 1-7): experience ->
    # representation -> state -> predict -> self-experience -> plasticity
    from .loop import NeuralLoop

    loop = NeuralLoop(brain, self_affirm_weight=0.0 if mode == "naive" else 0.15, log=None)

    matrix: list[dict[str, float]] = []
    for set_name in set_names:
        loop.live_block(set_name, epochs=cur.epochs_per_set, lr=LEARNING_RATE)
        row = metrics.evaluate_all(brain, set_names=set_names)
        matrix.append(row)
        brain.scheduler.end_block()  # promote this block's importance traces
        if mode == "consolidation":
            sleep(brain)
        log(f"  [{mode:13s}] after {set_name}: " + "  ".join(f"{k}={v:.2f}" for k, v in row.items()))

    return brain, matrix


def forgetting(matrix: list[dict[str, float]], set_names: list[str]) -> dict[str, float]:
    """max accuracy each set reached after its own training - final accuracy."""
    final = matrix[-1]
    out = {}
    for i, name in enumerate(set_names):
        best = max(row.get(name, 0.0) for row in matrix[i:])
        out[name] = best - final.get(name, 0.0)
    return out


def run_mode(mode: str, size: str, seed: int, out_dir: str, log=print) -> dict:
    set_names = Curriculum().set_names()
    log(f"\n=== {mode.upper()} ({size} brain) ===")
    brain, matrix = train_brain(mode=mode, size=size, seed=seed, log=log)

    para_acc, para_detail = metrics.evaluate_paraphrase(brain)
    comp_acc, comp_detail = metrics.evaluate_composition(brain)
    unseen = metrics.evaluate_unseen(brain)
    dist = metrics.measure_distribution(brain)
    brain.meta = {
        "mode": mode,
        "trained_sets": set_names,
        "external_memory_bytes": 0,
        "training_data_retained": False,
    }
    os.makedirs(out_dir, exist_ok=True)
    brain_path = os.path.join(out_dir, f"brain-{mode}.ncb")
    brain_bytes = brain.save(brain_path)

    report = {
        "mode": mode,
        "size": size,
        "matrix": [dict(r) for r in matrix],
        "final": metrics.evaluate_all(brain),
        "forgetting": forgetting(matrix, set_names),
        "paraphrase_accuracy": para_acc,
        "paraphrase": para_detail,
        "composition_accuracy": comp_acc,
        "composition": comp_detail,
        "unseen_combinations": unseen,
        "distribution": dist,
        "parameters_total": brain.net.parameter_count(),
        "parameters_nonzero": brain.net.nonzero_parameter_count(),
        "vocabulary_size": len(brain.vocab),
        "brain_file_bytes": brain_bytes,
        "brain_file": brain_path,
    }
    with open(os.path.join(out_dir, f"report-{mode}.json"), "w") as f:
        json.dump(report, f, indent=2)
    return report


def print_report(r: dict, log=print) -> None:
    names = list(r["final"].keys())
    log(f"\n--- {r['mode']} ---")
    log("retention matrix (accuracy after each learning block):")
    header = "          " + "".join(f"{n:>8}" for n in names)
    log(header)
    for i, row in enumerate(r["matrix"]):
        cells = "".join(f"{row.get(n, float('nan')):>8.2f}" if n in row else "      --" for n in names)
        log(f"after {names[i]:>2}:    {cells}")
    log("final:      " + "".join(f"{r['final'][n]:>8.2f}" for n in names))
    log(
        "forgetting: "
        + "".join(f"{n}: {r['forgetting'][n]:+.2f}  " for n in names)
    )
    log(f"paraphrase probes : {r['paraphrase_accuracy']:.2f}")
    for p in r["paraphrase"]:
        log(f"    {'OK ' if p['ok'] else 'MISS'} {p['surface']:<34} -> {p['got']}")
    log(f"composition chains: {r['composition_accuracy']:.2f}")
    for c in r["composition"]:
        hops = " -> ".join(f"{h['got']}({'OK' if h['ok'] else 'X'})" for h in c["hops"])
        log(f"    {'OK ' if c['ok'] else 'MISS'} {c['surface']:<45} {hops}")
    log("unseen combinations (structural reuse / honest refusal):")
    for u in r["unseen_combinations"]:
        tag = "novel" if u["novel"] else f"guess={u['got']}"
        log(f"    {u['surface']:<34} -> {tag} (conf {u['confidence']})")
    log(
        f"distribution: mean neuron overlap across concepts = "
        f"{r['distribution']['mean_overlap']:.2f} ({r['distribution']['n_pairs']} pairs)"
    )
    log(
        f"brain: {r['parameters_nonzero']}/{r['parameters_total']} live weights, "
        f"vocab {r['vocabulary_size']} concepts, file {r['brain_file_bytes']:,} bytes"
    )
    log("external memory: 0 files, 0 facts, no retrieval")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=list(MODES) + ["both"], default="both")
    ap.add_argument(
        "--size",
        choices=["compressed", "full"],
        default="compressed",
        help="compressed: capacity pressure, forgetting is real (default). "
        "full: over-provisioned control.",
    )
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="neuralcore_output")
    args = ap.parse_args()

    modes = list(MODES) if args.mode == "both" else [args.mode]
    reports = [run_mode(m, args.size, args.seed, args.out) for m in modes]

    print()
    print("=" * 74)
    print("CONTINUAL LEARNING — A then B then C then D (sequential, no replay)")
    print("=" * 74)
    for r in reports:
        print_report(r)

    if len(reports) == 2:
        n0, n1 = reports
        print()
        print("=" * 74)
        print("HEAD-TO-HEAD: naive plasticity vs metaplastic consolidation")
        print("=" * 74)
        for name in n0["final"]:
            print(
                f"  {name}: naive {n0['final'][name]*100:5.1f}% -> "
                f"consolidation {n1['final'][name]*100:5.1f}%   "
                f"(forgetting {n0['forgetting'][name]*100:+5.1f}% -> {n1['forgetting'][name]*100:+5.1f}%)"
        )
        print(
            f"  paraphrase : naive {n0['paraphrase_accuracy']*100:.0f}% -> "
            f"consolidation {n1['paraphrase_accuracy']*100:.0f}%"
        )
        print(
            f"  composition: naive {n0['composition_accuracy']*100:.0f}% -> "
            f"consolidation {n1['composition_accuracy']*100:.0f}%"
        )
        print(
            f"  brain file : naive {n0['brain_file_bytes']:,} B vs "
            f"consolidation {n1['brain_file_bytes']:,} B"
        )


if __name__ == "__main__":
    main()
