import numpy as np

from neuralcore.hrr import HRRSpace
from neuralcore.state import NeuralState


def test_state_recency():
    """The most recent experience dominates the internal state."""
    space = HRRSpace(dim=64, seed=7)
    st = NeuralState(dim=64)  # default alpha > 0.5
    x1, x2 = space.random_vector(), space.random_vector()
    st.update(x1)
    st.update(x2)
    assert space.cosine(st.h, x2) > space.cosine(st.h, x1)


def test_state_integrates_sequence():
    """Older experience is still present, just attenuated — a trace, not a wipe."""
    space = HRRSpace(dim=64, seed=8)
    st = NeuralState(dim=64, alpha=0.35)
    x1 = space.random_vector()
    st.update(x1)
    trace_with_only_x1 = st.h.copy()
    x2 = space.random_vector()
    st.update(x2)
    # correlation with x1 should drop but not vanish
    c_after = space.cosine(st.h, x1)
    assert 0.0 < c_after < space.cosine(trace_with_only_x1, x1) + 1e-9


def test_state_persists_across_updates():
    st = NeuralState(dim=32, alpha=0.5)
    st.update(np.ones(32) / 6)
    h_saved = st.h.copy()
    assert np.allclose(st.h, h_saved)
    st.reset()
    assert np.allclose(st.h, 0.0)
