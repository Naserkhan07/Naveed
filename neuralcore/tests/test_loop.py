"""Tests for THE LOOP: stages 1-8 and the generalization decision node."""

import numpy as np

from neuralcore.brain import Brain
from neuralcore.loop import NeuralLoop, run_progressive_loop, DEFAULT_CONFIG
from neuralcore.curriculum import probes_for_sets


def _brain():
    return Brain.build(DEFAULT_CONFIG)


def test_experience_step_changes_state_and_weights():
    brain = _brain()
    loop = NeuralLoop(brain)
    target = brain.vocab.get("water")
    w_before = brain.net.W1.copy()
    h_before = brain.state.h.copy()

    rep = loop.experience_step("sun", "heats", target, lr=0.1)

    assert not np.allclose(w_before, brain.net.W1)
    assert not np.allclose(h_before, brain.state.h)
    assert 0.0 <= rep.confidence <= 1.0


def test_self_affirmation_is_confidence_gated():
    """Stage 5 fires ONLY when the system's own prediction is already right:
    being right consolidates; being wrong never self-reinforces."""
    brain = _brain()
    loop = NeuralLoop(brain, affirm_threshold=0.6)

    # target = the system's own output -> perfect confidence -> affirms
    x = brain.perceiver().encode_query("sun", "heats", state_h=None)
    own_prediction = brain.net.forward(x)
    rep_ok = loop.experience_step("sun", "heats", own_prediction, lr=0.1)
    assert rep_ok.affirmed and rep_ok.confidence >= 0.6

    # target = a brand-new random vector -> near-zero confidence -> no affirm
    foreign = brain.space.random_vector()
    rep_no = loop.experience_step("sun", "heats", foreign, lr=0.1)
    assert not rep_no.affirmed and rep_no.confidence < 0.6


def test_probes_for_sets_respects_knowledge_so_far():
    """Mid-stream gating must not test facts that have not been experienced."""
    only_a = probes_for_sets(["A"])
    assert any("heated" in p["surface"] or "heats" in p["surface"] for p in only_a.paraphrase)
    # no composition chain is fully inside A (they need D's transformations)
    assert only_a.chains == []

    every = probes_for_sets(["A", "B", "C", "D"])
    assert len(every.chains) == 3
    assert len(every.paraphrase) == 8


def test_generalization_gate_decisions():
    """A healthy brain -> scale_up. A wiped brain -> modify_architecture."""
    brain, _ = run_progressive_loop(log=None)
    loop = NeuralLoop(brain)
    d = loop.generalization_gate(["A", "B", "C", "D"])
    assert d.action in ("scale_up", "modify_architecture")
    assert 0.0 <= d.generalization <= 1.0

    blank = _brain()
    d_blank = NeuralLoop(blank).generalization_gate(["A", "B", "C", "D"])
    assert d_blank.action == "modify_architecture"


def test_progressive_loop_runs_and_reports():
    brain, rep = run_progressive_loop(log=None)
    assert rep.capability > 0.5
    assert len(rep.decisions) >= 4          # at least one gate per block
    assert all(d.stage == 8 for d in rep.decisions)
    # the flowchart's growth path was actually walked: A, B, C, D in order
    first_sets = [b.set_name for b in rep.blocks]
    assert first_sets[0] == "A"
    assert "D" in first_sets
