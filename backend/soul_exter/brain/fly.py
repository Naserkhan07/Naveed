"""Numpy-only spiking fly brain.

29 glomeruli -> 26 projection neurons (lateral inhibition + divisive normalisation)
-> 140 Kenyon cells (fan-in 6, sparsity 0.09, LIF x 26 steps, winner-take-all)
-> 8 MBONs (attack, wait, retreat, investigate, hold, hedge, scale, abort) with an innate
8x29 instincts matrix + plastic KC->MBON weights updated by dopamine from realised R.
A central-complex ring attractor (16 heading cells) turns the signed senses into a direction.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from .senses import N_SENSE, SENSE_NAMES

N_GLOM, N_PN, N_KC, N_MBON, FAN_IN = 29, 26, 140, 8, 6
KC_SPARSITY = 0.09
LIF_STEPS = 26
N_RING = 16
MBON_NAMES = ["attack", "wait", "retreat", "investigate", "hold", "hedge", "scale", "abort"]
LR = 0.075
DOPA_EWMA = (0.65, 0.55)        # dopamine trace, reward baseline
W_CLAMP = 1.5
BASE_THR = 0.34
THR_Q = 0.93
ANATOMY = np.array([N_GLOM, N_PN, N_KC, N_MBON, FAN_IN, N_RING], dtype=np.int64)
SAVE_VERSION = 3

S = {n: i for i, n in enumerate(SENSE_NAMES)}
# senses that are direction-relative: they are flipped into the heading frame before the mushroom body
DIRECTIONAL = [S[k] for k in ("momentum", "body_conviction", "vwap_dist", "flow_imbalance", "book_pressure",
                              "ofi_ewma", "aggressor", "ccy_strength", "lead_lag", "range_pos55")]


def _instincts() -> np.ndarray:
    """innate 8x29 instincts (hand-wired, in the heading frame: +momentum = with the trade)"""
    M = np.zeros((N_MBON, N_GLOM))
    a, w, r, inv, h, hg, sc, ab = range(8)

    def put(row, **kw):
        for k, v in kw.items():
            M[row, S[k]] = v

    put(a, trend_up=.55, trend_down=-.55, momentum=.30, breakout_up=.30, breakout_down=-.30, efficiency=.40,
        session=.14, volume_surge=.12, body_conviction=.25, flow_imbalance=.25, aggressor=.14, ofi_ewma=.12,
        book_pressure=.10, var_ratio=.14, autocorr=.10, ccy_strength=.14, lead_lag=.12, peer_abs_rho=.06,
        spread_cost=-.40, liquidity_q=.10, vwap_dist=.06, stretch=-.06)
    put(w, trend_up=-.20, trend_down=-.20, efficiency=-.45, vol_regime=-.12, spread_cost=.20, session=-.14, corr_break=.06)
    put(r, trend_down=.55, trend_up=-.45, momentum=-.30, stretch=.28, spread_cost=.20, kurtosis=.10, flow_imbalance=-.30,
        body_conviction=-.20, breakout_down=.30)
    put(inv, corr_break=.60, vol_burst=.28, volume_surge=.24, skew=.10, kurtosis=.20, lead_lag=.16, atr_expansion=.16)
    put(h, trend_up=.14, efficiency=.10, peer_abs_rho=.14, session=.08)
    put(hg, peer_abs_rho=.45, corr_break=.24, kurtosis=.16, vol_regime=.18)
    put(sc, trend_up=.24, efficiency=.34, breakout_up=.26, volume_surge=.20, atr_expansion=.14)
    put(ab, spread_cost=.55, liquidity_q=-.34, vol_burst=.20, kurtosis=.18, stretch=.22, atr_expansion=.10)
    return M


class FlyBrain:
    def __init__(self, seed: int = 11):
        rng = np.random.default_rng(seed)
        self.rng = rng
        # glomeruli -> PN: sparse signed weights (each PN samples ~5 glomeruli)
        W = np.zeros((N_PN, N_GLOM))
        for p in range(N_PN):
            idx = rng.choice(N_GLOM, size=5, replace=False)
            W[p, idx] = rng.uniform(.5, 1.2, 5) * rng.choice([1, 1, 1, -1], 5)
        self.W_gp = W
        self.lat_inh = 0.45
        self.div_sigma = 0.35
        # PN -> KC (fan-in 6)
        self.fan = np.stack([rng.choice(N_PN, size=FAN_IN, replace=False) for _ in range(N_KC)])
        self.w_kc = rng.uniform(.6, 1.4, (N_KC, FAN_IN)) / math.sqrt(FAN_IN)
        self.kc_target = max(1, int(round(KC_SPARSITY * N_KC)))
        # MBON: innate + plastic
        self.instincts = _instincts()
        self.W_mb = np.zeros((N_MBON, N_KC))
        self.mb_gain = np.array([1.0, .9, .9, .9, .8, .8, .9, .9])
        self.mb_bias = np.array([-0.62, 0.30, -0.05, -0.05, 0.0, -0.05, -0.05, -0.10])
        # central complex ring
        th = 2 * np.pi * np.arange(N_RING) / N_RING
        self.ring_th = th
        self.ring_J = (np.cos(th[:, None] - th[None, :]) * 0.5 + 0.0) / N_RING * 2
        self.ring = np.zeros((0, N_RING))
        # learning state
        self.dopamine = 0.0
        self.baseline = 0.0
        self.n_updates = 0
        self.fatigue = 0.0
        self.hunger_hist: deque = deque(maxlen=60)
        self.last_act: dict = {}
        self._ring_state: np.ndarray | None = None

    # ---------------------------------------------------------- ring attractor
    def heading(self, cue: np.ndarray, state: np.ndarray | None):
        """cue: [N] signed direction evidence in [-1,1] -> (heading angle, direction, strength, ring state)"""
        n = cue.shape[0]
        if state is None or state.shape[0] != n:
            state = np.zeros((n, N_RING))
        th = self.ring_th
        theta_c = np.where(cue >= 0, 0.0, np.pi)
        inp = np.abs(cue)[:, None] * np.exp(2.2 * (np.cos(th[None, :] - theta_c[:, None]) - 1))
        r = state * 0.85
        for _ in range(8):
            rec = r @ self.ring_J.T
            r = np.maximum(0.0, 0.55 * r + 0.55 * rec + inp - 0.03 * r.sum(axis=1, keepdims=True))
            r = np.minimum(r, 3.0)
        cx = (r * np.cos(th)).sum(axis=1)
        sx = (r * np.sin(th)).sum(axis=1)
        ang = np.arctan2(sx, cx)
        tot = r.sum(axis=1) + 1e-9
        direction = np.where(np.cos(ang) >= 0, 1, -1)
        strength = np.clip(np.hypot(cx, sx) / tot, 0, 1) * np.tanh(tot)
        return ang, direction, strength, r

    # ---------------------------------------------------------------- forward
    def forward(self, sense: np.ndarray, extras: dict, learn_frame_state: bool = True) -> dict:
        """sense: [N,29] raw signed senses -> dict of activations"""
        n = sense.shape[0]
        g = sense.copy()
        # 1) heading from raw evidence
        comp = extras["comp"]
        bu, bd = sense[:, S["breakout_up"]], sense[:, S["breakout_down"]]
        cue = np.tanh(2.2 * (0.55 * comp + 0.22 * sense[:, S["momentum"]] + 0.14 * (bu - bd)
                             + 0.12 * sense[:, S["flow_imbalance"]] + 0.10 * sense[:, S["body_conviction"]]
                             + 0.05 * sense[:, S["book_pressure"]] + 0.06 * sense[:, S["lead_lag"]]
                             + 0.05 * sense[:, S["ccy_strength"]]))
        ang, d, strength, ring = self.heading(cue, self._ring_state)
        self._ring_state = ring
        # 2) into the heading frame
        g[:, DIRECTIONAL] = g[:, DIRECTIONAL] * d[:, None]
        cd = comp * d
        g[:, S["trend_up"]] = np.clip(cd, 0, 1)
        g[:, S["trend_down"]] = np.clip(-cd, 0, 1)
        g[:, S["breakout_up"]] = np.where(d > 0, bu, bd)
        g[:, S["breakout_down"]] = np.where(d > 0, bd, bu)
        g[:, S["stretch"]] = np.abs(g[:, S["stretch"]]) * np.sign(sense[:, S["stretch"]] * d) * -1 * -1
        # 3) antennal lobe -> PN: lateral inhibition + divisive normalisation
        pre = g @ self.W_gp.T
        pos = np.maximum(pre, 0)
        others = (pos.sum(axis=1, keepdims=True) - pos) / (N_PN - 1)
        pn = np.maximum(pos - self.lat_inh * others, 0)
        pn = pn / (self.div_sigma + pn.sum(axis=1, keepdims=True) / math.sqrt(N_PN))
        # 4) Kenyon cells: fan-in 6, LIF x 26 steps, winner-take-all at 9% sparsity
        cur = (pn[:, self.fan] * self.w_kc[None]).sum(axis=2)              # [N,140]
        cur = cur * 2.6
        v = np.zeros_like(cur); spikes = np.zeros_like(cur); first = np.full_like(cur, LIF_STEPS)
        theta = 0.55
        for t in range(LIF_STEPS):
            apl = 0.028 * spikes.sum(axis=1, keepdims=True)                 # global APL feedback inhibition
            v = v * 0.86 + 0.32 * (cur - apl)
            fire = v > theta
            first = np.where(fire & (spikes == 0), t, first)
            spikes += fire
            v = np.where(fire, 0.0, v)
        score = spikes + 0.02 * cur - first * 1e-3
        k = self.kc_target
        top = np.argpartition(-score, k - 1, axis=1)[:, :k]
        kc = np.zeros_like(cur)
        np.put_along_axis(kc, top, 1.0, axis=1)
        # 5) MBONs
        innate = g @ self.instincts.T                                       # [N,8]
        plastic = kc @ self.W_mb.T
        mb_pre = (innate + plastic + self.mb_bias) * self.mb_gain
        mb = np.tanh(np.maximum(mb_pre, 0) * 1.2)
        a, w, r_, inv, hd, hg, sc, ab = (mb[:, i] for i in range(8))
        hunger = np.clip(a - 0.45 * r_ - 0.30 * w - 0.35 * ab, 0, 1)
        out = {"g": g, "pn": pn, "kc": kc, "kc_idx": top, "mb": mb, "hunger": hunger, "heading": ang, "dir": d,
               "cue": cue, "strength": strength, "innate": innate}
        return out

    # ----------------------------------------------------------- thresholding
    def threshold(self, best_hunger: float, spread_pen: np.ndarray | float = 0.0) -> np.ndarray | float:
        self.hunger_hist.append(float(best_hunger))
        q = float(np.quantile(np.array(self.hunger_hist), THR_Q)) if len(self.hunger_hist) >= 5 else BASE_THR
        return 0.35 * q + 0.65 * BASE_THR + self.fatigue + spread_pen

    def decay_fatigue(self, dt: float):
        self.fatigue = max(0.0, self.fatigue - dt * 0.004)

    def struck(self):
        self.fatigue = min(0.12, self.fatigue + 0.03)

    # -------------------------------------------------------------- learning
    def reward(self, kc_idx: np.ndarray, R: float, action: int = 0) -> float:
        """dopamine from realised trade R (in units of risk).  Returns the dopamine level applied."""
        R = float(np.clip(R, -3, 3))
        self.baseline = DOPA_EWMA[1] * self.baseline + (1 - DOPA_EWMA[1]) * R
        rpe = R - self.baseline
        self.dopamine = DOPA_EWMA[0] * self.dopamine + (1 - DOPA_EWMA[0]) * float(np.tanh(rpe))
        d = self.dopamine
        idx = np.asarray(kc_idx, dtype=int)
        self.W_mb[action, idx] += LR * d
        self.W_mb[1, idx] -= 0.5 * LR * d           # wait opposes attack
        self.W_mb[2, idx] -= 0.35 * LR * d          # retreat
        if R < -0.5:
            self.W_mb[7, idx] += 0.25 * LR * abs(d)  # abort learns from bad outcomes
        np.clip(self.W_mb, -W_CLAMP, W_CLAMP, out=self.W_mb)
        self.n_updates += 1
        return d

    # ---------------------------------------------------------------- persist
    def save(self, path: str):
        np.savez(path, anatomy=ANATOMY, version=np.array([SAVE_VERSION]), W_mb=self.W_mb, W_gp=self.W_gp,
                 fan=self.fan, w_kc=self.w_kc, instincts=self.instincts,
                 state=np.array([self.dopamine, self.baseline, float(self.n_updates)]))

    def load(self, path: str) -> tuple[bool, str]:
        """shape-check; reject anything that isn't exactly today's anatomy"""
        try:
            z = np.load(path, allow_pickle=False)
            if "anatomy" not in z or not np.array_equal(z["anatomy"], ANATOMY):
                return False, "anatomy mismatch (old brain rejected)"
            if int(z["version"][0]) != SAVE_VERSION:
                return False, "version mismatch"
            exp = {"W_mb": (N_MBON, N_KC), "W_gp": (N_PN, N_GLOM), "fan": (N_KC, FAN_IN), "w_kc": (N_KC, FAN_IN),
                   "instincts": (N_MBON, N_GLOM)}
            for k, sh in exp.items():
                if k not in z or z[k].shape != sh:
                    return False, f"shape mismatch on {k}"
            if not np.isfinite(z["W_mb"]).all():
                return False, "non-finite weights"
            self.W_mb = np.clip(z["W_mb"].astype(float), -W_CLAMP, W_CLAMP)
            self.W_gp, self.fan, self.w_kc = z["W_gp"].astype(float), z["fan"].astype(int), z["w_kc"].astype(float)
            self.instincts = z["instincts"].astype(float)
            self.dopamine, self.baseline, self.n_updates = float(z["state"][0]), float(z["state"][1]), int(z["state"][2])
            return True, "ok"
        except Exception as e:      # noqa: BLE001
            return False, f"load failed: {type(e).__name__}"
