"""NEURAL DYNAMICS part 2: the predictive network and its plasticity.

A sparse predictive map W1 -> tanh -> top-k -> W2 trained with local,
error-driven updates (delta rule + one-step error transport). No optimizer
state, no batch replay, no external memory: every weight change is a direct
response to the current experience landing on the current state.

Sparsity (top-k winners) forces concepts to share neurons — distributed
knowledge, manifesto section 7 — and makes retention an honest competition
for resources rather than an artifact of dense noise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_EPS = 1e-9


@dataclass
class PlasticUpdate:
    """One experience's proposed weight change — the raw currency of learning.

    The scheduler reads these (to grow importance) and may attenuate them
    (to protect stable knowledge) before anything is applied.
    """

    dW1: np.ndarray
    db1: np.ndarray
    dW2: np.ndarray
    db2: np.ndarray

    def scale(self, lr: float) -> None:
        self.dW1 *= lr
        self.db1 *= lr
        self.dW2 *= lr
        self.db2 *= lr

    def squared_magnitude(self) -> float:
        return float(
            np.sum(self.dW1**2) + np.sum(self.db1**2) + np.sum(self.dW2**2) + np.sum(self.db2**2)
        )


class PredictiveNetwork:
    def __init__(self, dim: int, hidden: int, seed: int = 0, sparsity_k: int = 48):
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0.0, 1.0 / np.sqrt(dim), (hidden, dim))
        self.b1 = np.zeros(hidden)
        self.W2 = rng.normal(0.0, 1.0 / np.sqrt(hidden), (dim, hidden))
        self.b2 = np.zeros(dim)
        self.k = min(sparsity_k, hidden)
        self.last_activation: np.ndarray | None = None

    # -- forward dynamics ----------------------------------------------------

    def _hidden(self, x: np.ndarray) -> np.ndarray:
        a1 = np.tanh(self.W1 @ x + self.b1)
        if self.k < len(a1):
            thresh = np.partition(np.abs(a1), -self.k)[-self.k]
            a1 = np.where(np.abs(a1) >= thresh, a1, 0.0)
        return a1

    def forward(self, x: np.ndarray) -> np.ndarray:
        a1 = self._hidden(x)
        self.last_activation = a1
        return self.W2 @ a1 + self.b2

    # -- plasticity ------------------------------------------------------------

    def compute_update(
        self, x: np.ndarray, target: np.ndarray, weight_decay: float = 1e-5
    ) -> PlasticUpdate:
        """Local error-driven plasticity: surprise at the output, transported
        one step back; Oja-style stabilization keeps passively-used input
        weights near the statistics of recent experience."""
        a1 = self._hidden(x)
        y = self.W2 @ a1 + self.b2

        err = target - y                                # prediction error = surprise
        delta1 = (self.W2.T @ err) * (1.0 - a1**2)      # one-step error transport

        upd = PlasticUpdate(
            dW1=np.outer(delta1, x) - weight_decay * self.W1 * float(np.abs(a1).mean()),
            db1=delta1,
            dW2=np.outer(err, a1),
            db2=err,
        )
        return upd

    def apply_update(self, upd: PlasticUpdate) -> None:
        self.W1 += upd.dW1
        self.b1 += upd.db1
        self.W2 += upd.dW2
        self.b2 += upd.db2

    # -- bookkeeping -------------------------------------------------------------

    def named_parameters(self) -> dict[str, np.ndarray]:
        return {"W1": self.W1, "b1": self.b1, "W2": self.W2, "b2": self.b2}

    def parameter_count(self) -> int:
        return int(sum(p.size for p in self.named_parameters().values()))

    def nonzero_parameter_count(self, eps: float = 1e-12) -> int:
        return int(sum(np.count_nonzero(np.abs(p) > eps) for p in self.named_parameters().values()))

    def state_dict(self) -> dict:
        return {k: v.copy() for k, v in self.named_parameters().items()}

    def load_state_dict(self, sd: dict) -> None:
        self.W1 = np.asarray(sd["W1"], dtype=float).copy()
        self.b1 = np.asarray(sd["b1"], dtype=float).copy()
        self.W2 = np.asarray(sd["W2"], dtype=float).copy()
        self.b2 = np.asarray(sd["b2"], dtype=float).copy()
