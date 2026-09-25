"""THE core test: Learn A -> Learn D. Can it still use A? (manifesto §3)"""

import numpy as np
import pytest

from neuralcore import metrics
from neuralcore.experiments import train_brain


def test_sequential_sets_are_learned():
    brain, _ = train_brain(mode="consolidation", size="compressed", sets=["A", "B"], log=None)
    accs = metrics.evaluate_all(brain, set_names=["A", "B"])
    assert accs["A"] >= 0.75, f"set A should be usable, got {accs['A']}"
    assert accs["B"] >= 0.75, f"set B should be usable, got {accs['B']}"


def test_scheduler_protection_activates():
    """After learning, importance traces exist and gates actually bite."""
    brain_naive, _ = train_brain(mode="naive", size="compressed", sets=["A", "B"], log=None)
    brain_cons, _ = train_brain(mode="consolidation", size="compressed", sets=["A", "B"], log=None)
    assert brain_naive.scheduler.mean_gate() == 1.0
    assert brain_cons.scheduler.mean_gate() < 0.99, "protection should be active"


def test_consolidation_retains_at_least_naive():
    """The mechanism must never be worse than naive plasticity on retention."""
    _, m_naive = train_brain(mode="naive", size="compressed", sets=["A", "B", "C", "D"], log=None)
    _, m_cons = train_brain(mode="consolidation", size="compressed", sets=["A", "B", "C", "D"], log=None)
    assert m_cons[-1]["A"] >= m_naive[-1]["A"] - 0.05
    assert m_cons[-1]["B"] >= m_naive[-1]["B"] - 0.05


def test_distribution_of_knowledge():
    """Different concepts must share neurons (no grandmother cells)."""
    from neuralcore.curriculum import SETS
    from neuralcore.perception import normalize_word

    brain, _ = train_brain(mode="consolidation", size="compressed", sets=["A", "B"], log=None)
    perc = brain.perceiver()
    acts = []
    for s, r, _ in SETS["A"] + SETS["B"]:
        x = perc.encode_query(s, normalize_word(r), state_h=None)
        brain.net.forward(x)
        acts.append(set(np.nonzero(np.abs(brain.net.last_activation) > 1e-8)[0].tolist()))
    overlaps = [
        len(acts[i] & acts[j]) / len(acts[i] | acts[j])
        for i in range(len(acts))
        for j in range(i + 1, len(acts))
    ]
    assert np.mean(overlaps) > 0.03, "concepts should share neurons (distributed, not localist)"
    # ...but not collapsed: different concepts must not be identical
    assert max(overlaps) < 0.99
