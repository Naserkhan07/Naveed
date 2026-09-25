import numpy as np

from neuralcore.network import PredictiveNetwork


def _make_data(n=6, dim=64, seed=3):
    rng = np.random.default_rng(seed)
    xs = [rng.normal(0, 1 / np.sqrt(dim), dim) for _ in range(n)]
    ts = [rng.normal(0, 1 / np.sqrt(dim), dim) for _ in range(n)]
    return list(zip(xs, ts))


def test_network_learns_mapping():
    """Local error-driven plasticity can learn an associative map."""
    net = PredictiveNetwork(dim=64, hidden=128, seed=0, sparsity_k=32)
    data = _make_data()
    for _ in range(300):
        for x, t in data:
            upd = net.compute_update(x, t)
            upd.scale(0.05)
            net.apply_update(upd)
    scores = []
    for x, t in data:
        y = net.forward(x)
        scores.append(float(np.dot(y, t) / (np.linalg.norm(y) * np.linalg.norm(t) + 1e-9)))
    assert float(np.mean(scores)) > 0.8


def test_sparsity_is_enforced():
    net = PredictiveNetwork(dim=64, hidden=128, seed=1, sparsity_k=16)
    rng = np.random.default_rng(5)
    x = rng.normal(0, 1 / np.sqrt(64), 64)
    net.forward(x)
    active = np.count_nonzero(np.abs(net.last_activation) > 1e-8)
    assert active == 16


def test_update_is_local():
    """Weight change for one experience must not depend on any other stored
    experience — no replay buffer, no optimizer state."""
    net1 = PredictiveNetwork(dim=32, hidden=64, seed=2, sparsity_k=16)
    net2 = PredictiveNetwork(dim=32, hidden=64, seed=2, sparsity_k=16)
    rng = np.random.default_rng(9)
    x1, t1 = rng.normal(0, 0.1, 32), rng.normal(0, 0.1, 32)
    x2, t2 = rng.normal(0, 0.1, 32), rng.normal(0, 0.1, 32)

    upd1 = net1.compute_update(x1, t1)
    net2.compute_update(x2, t2)          # net2 experiences something else first
    upd1b = net1.compute_update(x1, t1)
    upd2b = net2.compute_update(x1, t1)  # same experience, different history

    assert np.allclose(upd1.dW1, upd1b.dW1)
    assert np.allclose(upd2b.dW1, upd1.dW1)
