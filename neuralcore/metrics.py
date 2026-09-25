"""MEASUREMENT: retention, forgetting, generalization, composition.

Everything here is computed from the brain alone — training data is consulted
only to score whether the dynamics produce the right answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .curriculum import SETS, build_probes
from .output import ask
from .perception import normalize_word


def evaluate_set(brain, set_name: str) -> tuple[float, int]:
    """Can the system still USE this experience block? (both directions)"""
    correct, total = 0, 0
    for s, r, o in SETS[set_name]:
        total += 1
        ans = ask(brain, s, r)
        if ans.concept == o:
            correct += 1
        inv_rel = normalize_word(f"inv_{r}")
        if inv_rel in brain.vocab.words:
            total += 1
            ans_inv = ask(brain, o, inv_rel)
            if ans_inv.concept == s:
                correct += 1
    return correct / max(1, total), total


def evaluate_all(brain, set_names=None) -> dict[str, float]:
    names = set_names or list(SETS.keys())
    return {n: evaluate_set(brain, n)[0] for n in names}


def evaluate_paraphrase(brain, probes=None) -> tuple[float, list[dict]]:
    probes = (probes.paraphrase if probes is not None else build_probes().paraphrase)
    results, correct = [], 0
    for p in probes:
        subj, rel = p["query"]
        ans = ask(brain, subj, rel)
        ok = ans.concept == normalize_word(p["expect"])
        correct += int(ok)
        results.append(
            {"surface": p["surface"], "expect": p["expect"], "got": ans.concept, "ok": ok}
        )
    return correct / len(probes), results


def evaluate_composition(brain, probes=None) -> tuple[float, list[dict]]:
    """Chain hops through the network's own outputs — no search, no lookup."""
    probes = (probes.chains if probes is not None else build_probes().chains)
    results, correct = [], 0
    for chain in probes:
        hops_ok, trace, entity = True, [], None
        for i, (s, r, expected) in enumerate(chain["hops"]):
            subj = s if i == 0 else entity
            ans = ask(brain, subj, r)
            hop_ok = ans.concept == normalize_word(expected)
            hops_ok = hops_ok and hop_ok
            trace.append(
                {"q": f"{subj} / {r} / ?", "expect": expected, "got": ans.concept, "ok": hop_ok}
            )
            entity = ans.concept if hop_ok else expected
        correct += int(hops_ok)
        results.append({"surface": chain["surface"], "hops": trace, "ok": hops_ok})
    return correct / len(probes), results


def evaluate_unseen(brain) -> list[dict]:
    """Unseen (entity, relation) combinations: honest scoring. 'novel' means
    the system declined to assert (confidence below threshold); otherwise a
    concept was produced — structural reuse."""
    results = []
    for p in build_probes().unseen_combos:
        subj, rel = p["query"]
        ans = ask(brain, subj, rel)
        results.append(
            {
                "surface": p["surface"],
                "got": ans.concept,
                "confidence": round(ans.confidence, 3),
                "novel": ans.confidence < 0.45,
            }
        )
    return results


def measure_distribution(brain, sample_sets=("A", "C")) -> dict[str, float]:
    """Do concepts share neurons? Mean pairwise Jaccard overlap of the active
    hidden sets across concepts from different blocks (manifesto section 7)."""
    perc = brain.perceiver()
    activations = []
    for set_name in sample_sets:
        for s, r, _o in SETS[set_name]:
            x = perc.encode_query(s, r, state_h=None)
            brain.net.forward(x)
            a = brain.net.last_activation
            activations.append(set(np.nonzero(np.abs(a) > 1e-8)[0].tolist()))
    overlaps = []
    for i in range(len(activations)):
        for j in range(i + 1, len(activations)):
            union = activations[i] | activations[j]
            if union:
                overlaps.append(len(activations[i] & activations[j]) / len(union))
    if not overlaps:
        return {"mean_overlap": 0.0, "n_pairs": 0}
    return {"mean_overlap": float(np.mean(overlaps)), "n_pairs": len(overlaps)}
