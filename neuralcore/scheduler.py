"""PLASTICITY SCHEDULER: metaplastic gates that stabilize important synapses.

The problem (manifesto section 3): learn A, then B, then C, then D — does A
survive? Naive plasticity overwrites old dynamics (the V11 result:
A 96% -> 6.8% after learning B).

The mechanism (segment-wise, in the spirit of Synaptic Intelligence but
applied to local plasticity): while a block of experience is being lived,
every synapse accumulates the squared magnitude of its own proposed changes.

    omega_pending  <-  sum over the block of (dw)^2

At the end of the block those traces are promoted: a synapse that kept
trying to move was load-bearing for what was just learned. During the NEXT
block, every synapse's plasticity is scaled by

    g = 1 / (1 + lambda * omega / mean(omega))

so heavily-loaded connections resist change while fresh (unused) synapses
stay fully plastic. Nothing is frozen and nothing is listed: the network
re-measures importance after every block, and sleep slowly decays omega so
protection tracks relevance over long horizons. This is
stability-through-plasticity — manifesto section 5 — not freezing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .network import PlasticUpdate


@dataclass
class SchedulerConfig:
    gate_lambda: float = 0.0     # 0 => naive plasticity; >0 enables protection
    min_gate: float = 1e-4       # a synapse never goes fully immutable
    sleep_decay: float = 0.98    # slow relaxation of importance during sleep


class MetaplasticScheduler:
    _ORDER = ("W1", "b1", "W2", "b2")
    _FIELD = {"W1": "dW1", "b1": "db1", "W2": "dW2", "b2": "db2"}

    def __init__(self, net, config: SchedulerConfig | None = None):
        self.net = net
        self.cfg = config or SchedulerConfig()
        self.omega = {name: np.zeros_like(p) for name, p in net.named_parameters().items()}
        self.pending = {name: np.zeros_like(p) for name, p in net.named_parameters().items()}

    def observe(self, upd: PlasticUpdate) -> None:
        """Accumulate this experience's PRE-gate proposed change into the
        current block's importance trace."""
        for name in self._ORDER:
            change = getattr(upd, self._FIELD[name])
            self.pending[name] += change**2

    def end_block(self) -> None:
        """Promote the block's traces: 'these synapses were load-bearing.'"""
        for name in self._ORDER:
            self.omega[name] = self.omega[name] + self.pending[name]
            self.pending[name] = np.zeros_like(self.pending[name])

    def protect(self, upd: PlasticUpdate) -> PlasticUpdate:
        """Return a gated copy: important synapses move less."""
        lam = self.cfg.gate_lambda
        if lam <= 0.0:
            return upd
        scale = float(np.mean([np.mean(o) for o in self.omega.values()])) + 1e-30
        gated = PlasticUpdate(
            dW1=upd.dW1.copy(), db1=upd.db1.copy(), dW2=upd.dW2.copy(), db2=upd.db2.copy()
        )
        for name in self._ORDER:
            rel = self.omega[name] / scale
            g = np.clip(1.0 / (1.0 + lam * rel), self.cfg.min_gate, 1.0)
            field = self._FIELD[name]
            setattr(gated, field, getattr(gated, field) * g)
        return gated

    def mean_gate(self) -> float:
        """Mean plasticity remaining across synapses (1.0 = fully plastic)."""
        lam = self.cfg.gate_lambda
        if lam <= 0.0:
            return 1.0
        scale = float(np.mean([np.mean(o) for o in self.omega.values()])) + 1e-30
        gates = []
        for o in self.omega.values():
            rel = o / scale
            gates.append(np.clip(1.0 / (1.0 + lam * rel), self.cfg.min_gate, 1.0).mean())
        return float(np.mean(gates))

    def sleep(self, rho: float | None = None) -> None:
        """Consolidation: relax importance so protection tracks relevance."""
        rho = self.cfg.sleep_decay if rho is None else rho
        for o in self.omega.values():
            o *= rho

    def add_neurons(self, delta: int) -> None:
        """Track structural growth: newborn synapses carry zero importance,
        i.e. they are born maximally plastic (gate = 1)."""
        delta = int(delta)
        if delta <= 0:
            return
        for store in (self.omega, self.pending):
            store["W1"] = np.vstack([store["W1"], np.zeros((delta, store["W1"].shape[1]))])
            store["b1"] = np.concatenate([store["b1"], np.zeros(delta)])
            store["W2"] = np.hstack([store["W2"], np.zeros((store["W2"].shape[0], delta))])

    def state_dict(self) -> dict:
        out = {f"omega_{k}": v.copy() for k, v in self.omega.items()}
        out.update({f"pending_{k}": v.copy() for k, v in self.pending.items()})
        return out

    def load_state_dict(self, sd: dict) -> None:
        for k in self._ORDER:
            if f"omega_{k}" in sd:
                self.omega[k] = np.asarray(sd[f"omega_{k}"], dtype=float).copy()
            if f"pending_{k}" in sd:
                self.pending[k] = np.asarray(sd[f"pending_{k}"], dtype=float).copy()
