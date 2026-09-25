import numpy as np
import pytest

from neuralcore.hrr import HRRSpace


def test_bind_unbind_roundtrip():
    space = HRRSpace(dim=256, seed=1)
    a, b = space.random_vector(), space.random_vector()
    c = space.bind(a, b)
    recovered = space.unbind(c, b)
    assert space.cosine(recovered, a) > 0.95


def test_unbound_key_is_convolution_identity():
    """b * b^-1 = delta: binding with the inverse key erases to the identity."""
    space = HRRSpace(dim=256, seed=2)
    b = space.random_vector()
    delta = np.zeros(space.dim)
    delta[0] = 1.0
    identity = space.bind(b, space.unbound_key(b))
    assert space.cosine(identity, delta) > 0.99


def test_binding_is_holographic():
    """A bound vector carries BOTH members, recoverable independently."""
    space = HRRSpace(dim=256, seed=3)
    a, b = space.random_vector(), space.random_vector()
    c = space.bind(a, b)
    assert space.cosine(c, a) < 0.2, "composite should not look like its parts"
    assert space.cosine(space.unbind(c, b), a) > 0.95
    assert space.cosine(space.unbind(c, a), b) > 0.95


def test_superpose_and_cleanup():
    """Multiple experiences share one space; cleanup recovers the right one."""
    space = HRRSpace(dim=256, seed=4)
    vecs = [space.random_vector() for _ in range(5)]
    noisy = vecs[2] + 0.5 * space.random_vector()
    best = max(vecs, key=lambda v: space.cosine(noisy, v))
    assert space.cosine(best, vecs[2]) > space.cosine(best, vecs[0])


def test_capacity_distinguishable():
    """With dim=256, a handful of superposed pairs stay mutually distinguishable."""
    space = HRRSpace(dim=256, seed=5)
    pairs = [(space.random_vector(), space.random_vector()) for _ in range(8)]
    memory = np.zeros(space.dim)
    for a, b in pairs:
        memory = memory + space.bind(a, b)
    correct = 0
    for idx, (a, b) in enumerate(pairs):
        got = space.unbind(memory, b)
        sims = [space.cosine(got, x) for x, _ in pairs]
        if int(np.argmax(sims)) == idx:
            correct += 1
    assert correct >= 6
