"""Tests for capability-per-byte: the compression frontier."""

import numpy as np

from neuralcore.brain import Brain
from neuralcore.compression import (
    capability_score,
    compression_curve,
    magnitude_prune,
    minimal_viable,
)
from neuralcore.experiments import train_brain


def _trained_brain():
    brain, _ = train_brain(mode="consolidation", log=None)
    return brain


def test_capability_score_bounds():
    brain = _trained_brain()
    cap = capability_score(brain)
    assert 0.0 < cap <= 1.0
    assert cap > 0.6, "trained brain should hold real capability"
    blank = Brain.build(brain.config)
    assert capability_score(blank) < cap


def test_pruning_zeroes_synapses_and_shrinks_bytes():
    brain = _trained_brain()
    before = brain.net.nonzero_parameter_count()
    bytes_before = brain.byte_size()
    pruned = magnitude_prune(brain, 0.5)
    assert pruned > 0
    assert brain.net.nonzero_parameter_count() < before
    assert brain.byte_size() <= bytes_before


def test_compression_curve_hurts_eventually():
    """Mild pruning is ~free; extreme pruning must cost capability.
    That trade-off IS the frontier the project measures."""
    brain = _trained_brain()
    curve = compression_curve(brain, fracs=(0.0, 0.2, 0.9))
    cap0, cap20, cap90 = (row["capability"] for row in curve)
    assert abs(cap20 - cap0) < 0.12, "20% pruning should be nearly free"
    assert cap90 < cap0, "90% pruning must cost capability"


def test_minimal_viable_picks_smallest_state():
    curve = [
        {"pruned_frac": 0.0, "brain_bytes": 1000, "capability": 0.90},
        {"pruned_frac": 0.4, "brain_bytes": 600, "capability": 0.87},
        {"pruned_frac": 0.9, "brain_bytes": 200, "capability": 0.40},
    ]
    mv = minimal_viable(curve, relative=0.95)
    assert mv["reachable"]
    assert mv["brain_bytes"] == 600
    assert mv["compression_ratio"] == 1000 / 600
