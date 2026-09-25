"""THE GROWTH EXPERIMENT — train on a big streamed corpus; the bot gets BIGGER.

    big experience stream (thousands of facts, sequential blocks)
            ↓
    NeuralCore loop (stages 1-7) block after block
            ↓
    two pressure signals checked continuously:
      - can't learn the new block        (final confidence low)
      - old knowledge decaying mid-block (sampled old-retention low)
            ↓
    either one -> the brain GROWS new silent neurons (byte size rises)
            ↓
    held-out evaluation on never-trained probes, brain file alone

Run:
    python3 -m neuralcore.grow                       # default scale
    python3 -m neuralcore.grow --facts 400           # more experience
    python3 -m neuralcore.grow --chat                # chat after training

Scale notes (honest): the address space (HRR dim) must scale with the number
of distinct experience-bindings — 256 dims hold ~tens of concepts, 1024 dims
hold thousands. The mechanism itself (growth policy, silent-neuron expansion,
streaming blocks, mid-block decay checks) is size-parametric: the same code
streams far more given more hardware. This sandbox verifies the full loop at
~1.3k-3k facts.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from .bigdata import (
    build_corpus,
    build_scale_probes,
    eval_chains,
    eval_facts,
    eval_unseen,
)
from .brain import Brain, BrainConfig
from .consolidation import sleep
from .growth import GrowthPolicy, GrowthTracker
from .loop import NeuralLoop
from .perception import Experience


def stream_block(brain, loop, tracker, block_facts, epochs, lr, old_sample, rng, old_floor):
    """Live one block with mid-block decay checks. Returns (mean, final, epochs_lived)."""
    exps = [Experience(sentence=f"the {s} {r} the {o}.", subject=s, relation=r, object=o)
            for s, r, o in block_facts]
    confs, steps = 0.0, 0
    final_conf = 0.0
    for epoch in range(epochs):
        brain.state.reset()
        e_confs = 0.0
        for exp in exps:
            target = brain.vocab.get(exp.object)
            rep = loop.experience_step(exp.subject, exp.relation, target, lr)
            confs += rep.confidence
            e_confs += rep.confidence
            steps += 1
        final_conf = e_confs / max(1, len(exps))
        # stage-8-in-miniature: is OLD knowledge decaying while we learn this?
        # if yes, grow NOW — new silent neurons absorb the rest of the block
        if old_sample and epoch < epochs - 1:
            sample = [old_sample[i] for i in rng.choice(len(old_sample),
                                                        size=min(80, len(old_sample)), replace=False)]
            old_acc, _ = eval_facts(brain, sample)
            if old_acc < old_floor:
                tracker.apply(brain, old_acc)
    return confs / max(1, steps), final_conf


def run(facts_per_domain: int = 224, n_relations: int = 8, dim: int = 1024,
        hidden0: int = 192, k: int = 64, epochs: int = 8, lr: float = 0.15,
        gate_lambda: float = 30.0, old_floor: float = 0.5, seed: int = 0,
        out_dir: str = "neuralcore_output", chat_after: bool = False) -> dict:
    t_start = time.time()
    corpus = build_corpus(seed=seed, facts_per_domain=facts_per_domain,
                          n_relations_per_domain=n_relations)
    probes = build_scale_probes(corpus, seed=seed + 1, n_retention=150,
                                n_unseen=80, n_chains=30)
    print(f"experience stream: {corpus.summary()}")
    print(f"held-out probes : {len(probes.retention)} retention, {len(probes.unseen)} unseen, "
          f"{len(probes.chains)} chains")

    cfg = BrainConfig(dim=dim, hidden=hidden0, sparsity_k=k, gate_lambda=gate_lambda, seed=seed)
    brain = Brain.build(cfg)
    loop = NeuralLoop(brain, self_affirm_weight=0.15, log=None)
    tracker = GrowthTracker(GrowthPolicy(confidence_floor=old_floor, cooldown=0, max_hidden=2048))

    start_bytes, start_hidden = brain.byte_size(), brain.net.hidden_size()
    print(f"\nbrain at birth : {brain.net.parameter_count():,} params, {start_bytes:,} B, "
          f"hidden {start_hidden}\n")

    report_blocks, old_sample = [], []
    rng = np.random.default_rng(seed + 2)
    print(f"streaming {len(corpus.blocks)} blocks through the loop:")
    for bi, block_idx in enumerate(corpus.blocks):
        block_facts = [corpus.facts[i] for i in block_idx]
        mean_conf, final_conf = stream_block(
            brain, loop, tracker, block_facts, epochs, lr, old_sample, rng, old_floor
        )
        brain.scheduler.end_block()
        sleep(brain)
        # post-block check: can't-learn-new signal
        if final_conf < old_floor:
            tracker.apply(brain, final_conf)
        old_sample.extend(block_facts)
        print(
            f"  block {bi:>2}: {len(block_facts):>3} facts | conf {mean_conf:.2f} "
            f"(final {final_conf:.2f}) | hidden {brain.net.hidden_size()} | "
            f"file {brain.byte_size():,} B"
        )
        report_blocks.append({
            "block": bi, "facts": len(block_facts), "mean_confidence": mean_conf,
            "final_confidence": final_conf, "hidden": brain.net.hidden_size(),
            "bytes": brain.byte_size(), "grew": tracker.events[-1]["neurons_added"]
            if tracker.events and tracker.events[-1].get("block") == bi else 0,
        })

    # -- held-out evaluation, brain alone -------------------------------------
    ret_acc, ret_conf = eval_facts(brain, probes.retention)
    unseen_stats = eval_unseen(brain, probes)
    chain_acc, _ = eval_chains(brain, probes.chains)

    end_bytes = brain.byte_size()
    print("\n" + "=" * 74)
    print("RESULT — the bot grew with its knowledge")
    print("=" * 74)
    print(f"brain size     : {start_bytes:,} B -> {end_bytes:,} B  "
          f"({end_bytes / max(1, start_bytes):.1f}x bigger)")
    print(f"hidden neurons : {start_hidden} -> {brain.net.hidden_size()}  "
          f"({len(tracker.events)} growth events)")
    print(f"vocabulary     : {len(brain.vocab)} concepts experienced")
    print(f"retention      : {ret_acc:.2f} (mean conf {ret_conf:.2f}) on {len(probes.retention)} facts")
    print(
        f"unseen pairs   : refusal {unseen_stats['refusal_rate']:.0%} | "
        f"answered {unseen_stats['answered']} | same-domain "
        f"{unseen_stats['domain_match_rate']:.0%} (chance {unseen_stats['chance']:.0%})"
    )
    print(f"composition    : {chain_acc:.2f} on {len(probes.chains)} chains")
    print(f"wall time      : {time.time() - t_start:.0f}s | external memory: 0 bytes, always")

    os.makedirs(out_dir, exist_ok=True)
    brain.meta = {
        "corpus": corpus.summary(),
        "growth_events": len(tracker.events),
        "training_data_retained": False,
        "external_memory_bytes": 0,
    }
    brain_path = os.path.join(out_dir, "brain-grown.ncb")
    n_bytes = brain.save(brain_path)
    report = {
        "corpus": corpus.summary(),
        "config": {"dim": dim, "hidden0": hidden0, "k": k, "epochs": epochs,
                   "lr": lr, "gate_lambda": gate_lambda, "old_floor": old_floor, "seed": seed},
        "start_bytes": start_bytes, "end_bytes": end_bytes,
        "start_hidden": start_hidden, "end_hidden": brain.net.hidden_size(),
        "growth_events": tracker.events,
        "blocks": report_blocks,
        "retention": {"accuracy": ret_acc, "mean_confidence": ret_conf, "n": len(probes.retention)},
        "unseen": unseen_stats,
        "composition": {"accuracy": chain_acc, "n": len(probes.chains)},
        "vocabulary": len(brain.vocab),
        "brain_file": brain_path, "brain_file_bytes": n_bytes,
        "wall_seconds": round(time.time() - t_start, 1),
        "external_memory_bytes": 0,
    }
    with open(os.path.join(out_dir, "growth-report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nbrain saved    : {brain_path} ({n_bytes:,} B)")
    print(f"talk to it     : python3 -m neuralcore.chat {brain_path}")

    if chat_after:
        from .chat import repl
        repl(brain)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--facts", type=int, default=224, help="facts per domain (6 domains)")
    ap.add_argument("--relations", type=int, default=8, help="relations per domain")
    ap.add_argument("--dim", type=int, default=1024, help="address-space size")
    ap.add_argument("--hidden0", type=int, default=192, help="starting hidden neurons")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--lr", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="neuralcore_output")
    ap.add_argument("--chat", action="store_true", help="drop into the REPL after training")
    args = ap.parse_args()
    run(facts_per_domain=args.facts, n_relations=args.relations, dim=args.dim,
        hidden0=args.hidden0, epochs=args.epochs, lr=args.lr, seed=args.seed,
        out_dir=args.out, chat_after=args.chat)


if __name__ == "__main__":
    main()
