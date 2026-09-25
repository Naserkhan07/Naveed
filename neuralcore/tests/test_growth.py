"""Tests for structural growth (the bot gets bigger) and the big corpus."""

import numpy as np
import pytest

from neuralcore.bigdata import (
    build_corpus,
    build_scale_probes,
    eval_facts,
)
from neuralcore.brain import Brain, BrainConfig
from neuralcore.growth import GrowthPolicy, GrowthTracker
from neuralcore.loop import NeuralLoop
from neuralcore.perception import EmergingVocabulary, Experience, HRRSpace


# -- silent-neuron expansion ---------------------------------------------------

def test_add_neurons_preserves_weights_exactly():
    net = Brain.build(BrainConfig(dim=32, hidden=16, sparsity_k=8)).net
    W1, b1, W2, b2 = net.W1.copy(), net.b1.copy(), net.W2.copy(), net.b2.copy()
    rng = np.random.default_rng(0)
    hidden = net.add_neurons(8, rng)
    assert hidden == 24
    assert np.allclose(net.W1[:16], W1)
    assert np.allclose(net.b1[:16], b1)
    assert np.allclose(net.W2[:, :16], W2)
    assert np.allclose(net.b2, b2)
    # newborn readouts are (near-)silent
    assert np.max(np.abs(net.W2[:, 16:])) < 0.05


def test_growth_does_not_change_answers():
    """A grown brain answers identically BEFORE any new learning."""
    from neuralcore.output import ask

    brain = Brain.build(BrainConfig(dim=64, hidden=64, sparsity_k=16, gate_lambda=15.0, seed=3))
    target = brain.vocab.get("water")
    loop = NeuralLoop(brain)
    for _ in range(60):
        loop.experience_step("sun", "heats", target, lr=0.1)
    before = ask(brain, "sun", "heats")

    brain.grow(64)
    after = ask(brain, "sun", "heats")

    assert after.concept == before.concept
    assert abs(after.confidence - before.confidence) < 0.12, "growth must barely disturb dynamics"


def test_grown_neurons_learn_new_experience():
    """After growth, the expanded brain learns a NEW experience block."""
    brain = Brain.build(BrainConfig(dim=64, hidden=48, sparsity_k=12, gate_lambda=15.0, seed=4))
    loop = NeuralLoop(brain, self_affirm_weight=0.0)
    water = brain.vocab.get("water")
    for _ in range(40):
        loop.experience_step("sun", "heats", water, lr=0.1)

    brain.scheduler.end_block()      # promote block-A importance: protection ON
    brain.grow(48)
    fire = brain.vocab.get("wood")
    for _ in range(60):
        loop.experience_step("fire", "burns", fire, lr=0.1)
    brain.scheduler.end_block()

    from neuralcore.output import ask

    assert ask(brain, "fire", "burns").concept == "wood"
    assert ask(brain, "sun", "heats").concept == "water"   # old knowledge survives


def test_growth_tracker_policy_and_ceiling():
    brain = Brain.build(BrainConfig(dim=32, hidden=32, sparsity_k=8))
    tracker = GrowthTracker(GrowthPolicy(confidence_floor=0.6, delta_frac=0.5, max_hidden=48))
    assert tracker.apply(brain, 0.9) == 0                  # confident -> no growth
    assert tracker.apply(brain, 0.2) == 16                 # pressure -> grows
    assert brain.net.hidden_size() == 48
    assert tracker.apply(brain, 0.2) == 0                  # ceiling reached


# -- vectorized vocabulary cleanup -----------------------------------------------

def test_vectorized_nearest_matches_bruteforce():
    space = HRRSpace(dim=128, seed=9)
    vocab = EmergingVocabulary(space)
    for w in ["alpha", "beta", "gamma", "delta", "epsilon"]:
        vocab.get(w)
    for _ in range(20):
        v = space.random_vector()
        got = vocab.nearest(v)
        sims = {w: space.cosine(v, vec) for w, vec in zip(vocab.order, vocab.vectors)}
        best = max(sims, key=sims.get)
        assert got[0] == best


# -- the big corpus ----------------------------------------------------------------

def test_corpus_deterministic_and_valid():
    c1 = build_corpus(seed=0, facts_per_domain=80)
    c2 = build_corpus(seed=0, facts_per_domain=80)
    assert c1.facts == c2.facts
    assert all(len(b) > 0 for b in c1.blocks)
    # (subject, relation) pairs are unique across the stream
    pairs = [(s, r) for s, r, _ in c1.facts]
    assert len(pairs) == len(set(pairs))


def test_scale_probes_disjoint_from_training():
    corpus = build_corpus(seed=2, facts_per_domain=60)
    probes = build_scale_probes(corpus, seed=3, n_retention=50, n_unseen=40, n_chains=5)
    # retention probes ARE trained facts
    assert all((s, r) in corpus.train_pairs for s, r, _ in probes.retention)
    # unseen pairs are NOT
    assert all((s, r) not in corpus.train_pairs for s, r in probes.unseen)
    # chain facts are trained facts
    trained = set(corpus.facts)
    for chain in probes.chains:
        for fact in chain:
            assert fact in trained


def test_growth_demo_small_stream_learns_and_grows():
    """End-to-end miniature of the growth experiment on a tiny stream.
    Scale respects the address-space law: ~72 bindings in dim=128 keeps
    inputs separable (the same ratio as the toy curriculum)."""
    corpus = build_corpus(seed=5, facts_per_domain=12, n_relations_per_domain=6)
    probes = build_scale_probes(corpus, seed=6, n_retention=24, n_unseen=10, n_chains=3)
    brain = Brain.build(BrainConfig(dim=128, hidden=48, sparsity_k=16, gate_lambda=15.0, seed=5))
    loop = NeuralLoop(brain, self_affirm_weight=0.15, log=None)
    tracker = GrowthTracker(GrowthPolicy(confidence_floor=0.75, delta_frac=0.5, max_hidden=192))

    grew = 0
    for block_idx in corpus.blocks:
        exps = [Experience(sentence=f"the {s} {r} the {o}.", subject=s, relation=r, object=o)
                for s, r, o in (corpus.facts[i] for i in block_idx)]
        for _ in range(4):            # a few passes, like the real stream
            brain.state.reset()
            for exp in exps:
                target = brain.vocab.get(exp.object)
                loop.experience_step(exp.subject, exp.relation, target, lr=0.12)
        brain.scheduler.end_block()   # promote importance before the next block
        grew += int(tracker.apply(brain, 0.05) > 0)   # low floor -> policy decides

    acc, conf = eval_facts(brain, probes.retention)
    assert grew >= 1, "the growth path should have fired at least once"
    assert acc > 0.3, f"tiny stream should still teach something, got {acc}"
