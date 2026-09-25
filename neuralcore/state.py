"""NEURAL DYNAMICS part 1: persistent internal state.

    State(t) -> experience(t) -> State(t+1) -> experience(t+1) -> ...

The system never sees an experience "cold": every input lands on a brain
that already carries a leaky trace of everything just before it. This is
what later lets sequential experience (stories, context) shape processing —
manifesto section 6.
"""

from __future__ import annotations

import numpy as np

_EPS = 1e-9


class NeuralState:
    def __init__(self, dim: int, alpha: float = 0.6):
        # alpha > 0.5 so the most recent experience leads the trace, while
        # (1-alpha) keeps the preceding context present underneath it.
        self.dim = dim
        self.alpha = alpha          # how strongly new experience overwrites the trace
        self.h = np.zeros(dim)

    def update(self, activation: np.ndarray) -> np.ndarray:
        """One step of state evolution. Returns the new state."""
        h_new = (1.0 - self.alpha) * self.h + self.alpha * activation
        n = np.linalg.norm(h_new)
        self.h = h_new / n if n > _EPS else h_new
        return self.h

    def reset(self) -> None:
        self.h = np.zeros(self.dim)

    def state_dict(self) -> dict:
        return {"h": self.h.copy(), "alpha": np.array([self.alpha])}

    def load_state_dict(self, sd: dict) -> None:
        self.h = np.asarray(sd["h"], dtype=float).copy()
        self.alpha = float(np.asarray(sd["alpha"]).ravel()[0])
