"""Correlation module — computed from the rolling tape (never scraped), <= once / 4 s.

Pairwise Pearson at 1/5/15-bar horizons, strongest-peer |rho|>=0.72 features,
regression residual z (clamped +-4), lead-lag edge, currency-strength composite
per FX leg (z-summed, standardised).  Operator rule: correlation trades only in
the strong band |rho| >= 0.90 (green +90..+99 / red -90..-99); a table older than
60 s blocks correlation trades.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .universe import CURRENCIES, SYM_INDEX, UNIVERSE

MIN_INTERVAL = 4.0
STALE_S = 60.0
PEER_MIN = 0.72
STRONG = 0.90
BREAK_SHIFT = 0.45


def _pearson_rows(X: np.ndarray) -> np.ndarray:
    X = X - X.mean(axis=1, keepdims=True)
    sd = np.sqrt((X * X).sum(axis=1, keepdims=True)) + 1e-18
    Z = X / sd
    return np.clip(Z @ Z.T, -1, 1)


def band(rho: float) -> str:
    a = abs(rho)
    if a >= STRONG:
        return "green" if rho > 0 else "red"
    return "none"


def rho_pct(rho: float) -> int:
    """display integer: sign * 90..99 in the strong band (capped at 99)"""
    return int(math.copysign(min(99, int(abs(rho) * 100)), rho))


@dataclass
class CorrTable:
    at: float = -1e9                        # virtual-clock time of computation
    bars: int = 0
    rho: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    rho1: np.ndarray | None = None
    rho5: np.ndarray | None = None
    rho15: np.ndarray | None = None
    peer: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))
    peer_rho: np.ndarray = field(default_factory=lambda: np.zeros(0))
    resid_z: np.ndarray = field(default_factory=lambda: np.zeros(0))
    leadlag: np.ndarray = field(default_factory=lambda: np.zeros(0))
    break_shift: np.ndarray = field(default_factory=lambda: np.zeros(0))
    rho_short: np.ndarray = field(default_factory=lambda: np.zeros(0))
    ccy_strength: dict = field(default_factory=dict)
    ccy_spread: np.ndarray = field(default_factory=lambda: np.zeros(0))
    peer_resid5: np.ndarray = field(default_factory=lambda: np.zeros(0))


class CorrelationEngine:
    def __init__(self):
        self.table = CorrTable()
        self.n = len(UNIVERSE)
        self.computes = 0
        self.fx_pairs = [(i.idx, CURRENCIES.index(i.fx[0]), CURRENCIES.index(i.fx[1])) for i in UNIVERSE if i.fx]
        self.cls = np.array([i.cls for i in UNIVERSE])

    # ------------------------------------------------------------- update
    def update(self, tape, now: float, force: bool = False) -> CorrTable:
        if not force and now - self.table.at < MIN_INTERVAL:
            return self.table
        nb = tape.nbars
        if nb < 80:
            return self.table
        L = min(nb, 300)
        C = tape.C[:, -L:]
        lc = np.log(np.maximum(C, 1e-12))
        r1 = np.diff(lc, axis=1)
        rho1 = _pearson_rows(r1[:, -60:])
        r5 = lc[:, 5:] - lc[:, :-5]
        rho5 = _pearson_rows(r5[:, -200:])
        r15 = lc[:, 15:] - lc[:, :-15]
        rho15 = _pearson_rows(r15)
        stack = np.stack([rho1, rho5, rho15])
        rho = np.median(stack, axis=0)                        # signed, robust across horizons
        np.fill_diagonal(rho, 0.0)
        ar = np.abs(rho)
        peer = ar.argmax(axis=1)
        prho = rho[np.arange(self.n), peer]
        # regression residual z vs. strongest peer (1-bar returns, last 60; window of last 5)
        W = 60
        X = r1[:, -W:]
        resid_z = np.zeros(self.n); leadlag = np.zeros(self.n); resid5 = np.zeros(self.n)
        rho_short = np.zeros(self.n)
        sig1 = X.std(axis=1) + 1e-12
        for i in range(self.n):
            j = int(peer[i])
            xi, xj = X[i], X[j]
            vj = float(np.dot(xj - xj.mean(), xj - xj.mean())) + 1e-18
            beta = float(np.dot(xi - xi.mean(), xj - xj.mean())) / vj
            e = xi - beta * xj
            sd = e.std() + 1e-12
            s5 = float(e[-5:].sum())
            resid5[i] = s5
            resid_z[i] = float(np.clip(s5 / (sd * math.sqrt(5)), -4, 4))
            # lead-lag over last 100 bars: does j lead i ?
            a, b = r1[i, -100:], r1[j, -100:]
            c_ji = np.corrcoef(a[1:], b[:-1])[0, 1] if a.std() > 0 and b.std() > 0 else 0.0
            c_ij = np.corrcoef(b[1:], a[:-1])[0, 1] if a.std() > 0 and b.std() > 0 else 0.0
            edge = (c_ji - c_ij)
            last_j = float(b[-1]) / (sig1[j] if sig1[j] > 0 else 1)
            sgn = 1.0 if prho[i] >= 0 else -1.0
            leadlag[i] = float(np.tanh(4 * edge) * np.tanh(last_j) * sgn)
            s = r1[i, -30:]; t = r1[j, -30:]
            rho_short[i] = float(np.corrcoef(s, t)[0, 1]) if s.std() > 0 and t.std() > 0 else 0.0
        break_shift = np.abs(prho - rho_short) * (np.abs(prho) >= PEER_MIN)
        # currency strength (15-bar return z, summed per currency, standardised)
        z15 = r15[:, -1] / (sig1 * math.sqrt(15))
        cs = np.zeros(len(CURRENCIES)); cnt = np.zeros(len(CURRENCIES))
        for idx, b, q in self.fx_pairs:
            cs[b] += z15[idx]; cs[q] -= z15[idx]; cnt[b] += 1; cnt[q] += 1
        cs = cs / np.maximum(cnt, 1)
        cs = (cs - cs.mean()) / (cs.std() + 1e-9)
        spread = np.zeros(self.n)
        for idx, b, q in self.fx_pairs:
            spread[idx] = float(np.tanh((cs[b] - cs[q]) / 2.0))
        for c in set(self.cls):
            if c == "forex":
                continue
            ids = np.where(self.cls == c)[0]
            zz = z15[ids]
            spread[ids] = np.tanh((zz - zz.mean()) / (zz.std() + 1e-9) / 2.0) * 0.6
        t = self.table
        t.at, t.bars = now, tape.nbars
        t.rho, t.rho1, t.rho5, t.rho15 = rho, rho1, rho5, rho15
        t.peer, t.peer_rho, t.resid_z, t.leadlag = peer, prho, resid_z, leadlag
        t.break_shift, t.rho_short = break_shift, rho_short
        t.ccy_strength = {c: round(float(cs[k]), 3) for k, c in enumerate(CURRENCIES)}
        t.ccy_spread, t.peer_resid5 = spread, resid5
        self.computes += 1
        return t

    def fresh(self, now: float) -> bool:
        return (now - self.table.at) <= STALE_S and self.table.bars > 0

    # ------------------------------------------------------------ features
    def features(self, idx: int) -> dict:
        t = self.table
        if t.bars == 0:
            return {"peer": -1, "rho": 0.0, "abs": 0.0, "z": 0.0, "lead": 0.0, "brk": 0.0, "ccy": 0.0}
        prho = float(t.peer_rho[idx])
        return {"peer": int(t.peer[idx]), "rho": prho, "abs": abs(prho) if abs(prho) >= PEER_MIN else 0.0,
                "z": float(t.resid_z[idx]), "lead": float(t.leadlag[idx]),
                "brk": float(min(1.0, t.break_shift[idx] / 0.8)), "ccy": float(t.ccy_spread[idx])}

    def snapshot(self, now: float, limit: int = 40) -> dict:
        t = self.table
        strong = []
        if t.bars:
            iu = np.triu_indices(self.n, 1)
            vals = t.rho[iu]
            order = np.argsort(-np.abs(vals))
            for k in order[:600]:
                v = float(vals[k])
                if abs(v) < STRONG:
                    break
                a, b = int(iu[0][k]), int(iu[1][k])
                strong.append({"a": UNIVERSE[a].sym, "b": UNIVERSE[b].sym, "rho": rho_pct(v), "band": band(v)})
            n_strong = len(strong)
            strong = strong[:limit]
        else:
            n_strong = 0
        peers = []
        if t.bars:
            for i in np.argsort(-np.abs(t.resid_z))[:12]:
                peers.append({"s": UNIVERSE[int(i)].sym, "peer": UNIVERSE[int(t.peer[i])].sym,
                              "rho": round(float(t.peer_rho[i]), 3), "z": round(float(t.resid_z[i]), 2),
                              "break": round(float(t.break_shift[i]), 2)})
        return {"age_s": round(now - t.at, 1), "fresh": self.fresh(now), "computes": self.computes,
                "n_strong": n_strong, "strong_pairs": strong, "top_residual": peers,
                "ccy_strength": t.ccy_strength, "rule": "correlation trades only when |rho|>=0.90 and table age<=60s"}
