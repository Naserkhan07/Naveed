"""Synthetic regime tape (+ optional live 1-minute merge).

Per instrument: regime (trend_up/trend_down/range/squeeze), momentum OU, session
vol, news bursts.  Shared factors: global macro OU + risk-sentiment OU with
per-currency betas + small per-currency OUs, plus group factors for the other
classes, so FX forms real correlation blocs.
    ret = drift + momo + 0.62*macro + 0.70*ccy_shock + idio
History (~340 bars of 60 s) is seeded with the very same generator.
"""
from __future__ import annotations

import math
import time
from typing import Callable

import numpy as np

from .universe import CCY_BETA, CURRENCIES, UNIVERSE, Instrument

BAR_S = 60.0
CAP = 520
SEED_BARS = 340
REGIMES = ("trend_up", "trend_down", "range", "squeeze")
REGIME_P = np.array([.30, .30, .28, .12])
GROUPS = ["risk", "crypto", "us", "eu", "asia", "tech", "fin", "energy", "def", "cons", "ind", "metal", "agri", "rates"]
K_FX_MACRO = 5.0        # FX factor amplitude (sigma units per bar for |beta diff| = 1)
K_GROUP = 3.8
W_MACRO, W_CCY = 0.62, 0.70


def _ou_step(x, phi_bar, sd, f, rng):
    """exact OU step for a sub-interval of f bars; stationary sd `sd`"""
    phi = phi_bar ** f
    return x * phi + sd * math.sqrt(max(1 - phi * phi, 0.0)) * rng.standard_normal(np.shape(x)) if np.shape(x) else \
        x * phi + sd * math.sqrt(max(1 - phi * phi, 0.0)) * rng.standard_normal()


class Tape:
    def __init__(self, seed: int = 7, start_ts: float | None = None):
        self.rng = np.random.default_rng(seed)
        self.u: list[Instrument] = UNIVERSE
        self.n = len(self.u)
        n = self.n
        self.ts = start_ts if start_ts is not None else time.time()
        self.t_in_bar = 0.0
        self._acc = 0.0
        self.price = np.array([i.price for i in self.u], dtype=float)
        self.sigma = np.array([i.sigma for i in self.u])
        self.idio = np.array([i.idio for i in self.u])
        self.spread_bps = np.array([i.spread_bps for i in self.u])
        self.basevol = np.array([i.vol for i in self.u])
        self.cls = np.array([i.cls for i in self.u])
        self.cls_ids = {c: np.where(self.cls == c)[0] for c in set(self.cls)}
        # history ring buffers [n, CAP]; latest column is the last CLOSED bar
        self.O = np.zeros((n, CAP)); self.H = np.zeros((n, CAP)); self.Lo = np.zeros((n, CAP))
        self.C = np.zeros((n, CAP)); self.V = np.zeros((n, CAP)); self.BV = np.zeros((n, CAP))
        self.SP = np.zeros((n, CAP))       # spread (bps) per bar
        self.nbars = 0
        # forming bar
        self.fo = self.price.copy(); self.fh = self.price.copy(); self.fl = self.price.copy()
        self.fv = np.zeros(n); self.fbv = np.zeros(n)
        self.tick_signed = np.zeros(n)      # tick-rule signed volume in forming bar
        self.tick_signed_hist = np.zeros((n, CAP))
        self.open_px = self.price.copy()
        # regimes
        self.regime = self.rng.choice(4, size=n, p=REGIME_P)
        self.regime_left = self.rng.uniform(20, 90, n)          # bars
        self.mu = self.rng.uniform(.12, .30, n)                 # trend drift (sigma / bar)
        self.anchor = np.log(self.price)
        self.phi = self.rng.uniform(.80, .90, n)
        self.share = self.rng.uniform(.14, .24, n)
        self.momo = self.rng.standard_normal(n) * np.sqrt(self.share)
        # factors
        self.macro = 0.0; self.risk = 0.0
        self.ccy = {c: 0.0 for c in CURRENCIES}
        self.grp = {g: 0.0 for g in GROUPS}
        self.burst = {g: 0.0 for g in GROUPS + CURRENCIES}
        self.fx_e = np.zeros(n)
        self.fx_b = np.full(n, -1); self.fx_q = np.full(n, -1)
        for i in self.u:
            if i.fx:
                self.fx_e[i.idx] = CCY_BETA[i.fx[0]] - CCY_BETA[i.fx[1]]
                self.fx_b[i.idx] = CURRENCIES.index(i.fx[0]); self.fx_q[i.idx] = CURRENCIES.index(i.fx[1])
        self.gload = np.zeros((n, len(GROUPS)))
        for i in self.u:
            for g, v in i.loads.items():
                self.gload[i.idx, GROUPS.index(g)] = v
        self.is_fx = self.fx_b >= 0
        self.live_mode = "SYNTHETIC (offline)"
        self.live_n = 0
        self.live_idx: set = set()
        self._live_bars: dict[int, tuple] = {}     # idx -> (ts, o,h,l,c,v,bv)
        self.listeners: list[Callable[[np.ndarray, np.ndarray, float], None]] = []
        self.news: list[dict] = []
        self.vscale = np.ones(n)
        self._no_drift = False
        self._calibrate()
        self._seed_history()

    # -------------------------------------------------------------- sessions
    def session_mult(self, ts: float) -> np.ndarray:
        h = (ts % 86400) / 3600.0
        wd = int(ts // 86400 + 4) % 7          # 0 = Monday
        m = np.ones(self.n)
        fx = 0.72 + 0.45 * math.exp(-((h - 9.5) / 3.2) ** 2) + 0.7 * math.exp(-((h - 14.0) / 2.4) ** 2)
        us = 1.55 if 13.5 <= h < 20.0 else (0.85 if 7 <= h < 13.5 else 0.45)
        asia = 1.5 if 0 <= h < 6.5 else 0.5
        eu = 1.4 if 7 <= h < 16 else 0.5
        crypto = 0.9 + 0.2 * math.exp(-((h - 15) / 4) ** 2)
        m[self.cls_ids.get("forex", [])] = fx
        m[self.cls_ids.get("crypto", [])] = crypto
        for c in ("stock", "option"):
            m[self.cls_ids.get(c, [])] = us
        for i in self.u:
            if i.cls in ("index", "future"):
                g = "us" if i.loads.get("us") else ("eu" if i.loads.get("eu") else ("asia" if i.loads.get("asia") else None))
                m[i.idx] = us if g == "us" else (eu if g == "eu" else (asia if g == "asia" else 1.0))
        if wd >= 5:                                             # weekend: crypto only lively
            for c in ("forex", "stock", "index", "future", "option"):
                m[self.cls_ids.get(c, [])] *= 0.55
        return m

    def session_quality(self, ts: float) -> np.ndarray:
        return np.clip(self.session_mult(ts) / 1.5, 0, 1)

    # ----------------------------------------------------------------- core
    def _roll_regimes(self, f: float):
        self.regime_left -= f
        done = np.where(self.regime_left <= 0)[0]
        for i in done:
            prev = self.regime[i]
            if prev == 3 and self.rng.random() < .65:            # squeeze -> expansion
                self.regime[i] = self.rng.choice([0, 1])
            else:
                self.regime[i] = self.rng.choice(4, p=REGIME_P)
            self.regime_left[i] = self.rng.uniform(18, 95)
            self.mu[i] = self.rng.uniform(.12, .30)
            self.anchor[i] = math.log(self.price[i])

    def _step(self, dt: float, ts: float, seeding: bool = False):
        rng = self.rng
        f = dt / BAR_S
        sf = math.sqrt(f)
        # factors
        self.macro = _ou_step(self.macro, .08, 1.0, f, rng)
        self.risk = _ou_step(self.risk, .06, 1.0, f, rng)
        for c in CURRENCIES:
            self.ccy[c] = _ou_step(self.ccy[c], .08, .35, f, rng)
        for g in GROUPS:
            self.grp[g] = _ou_step(self.grp[g], .08, 1.0, f, rng)
        # news bursts (Poisson ~ once / 25 min / group)
        if rng.random() < f / 25.0 * 4:
            key = rng.choice(GROUPS + CURRENCIES)
            self.burst[key] += rng.uniform(1.0, 3.0)
            sgn = rng.choice([-1, 1])
            if key in self.ccy:
                self.ccy[key] += sgn * 1.4
            elif key == "risk":
                self.risk += sgn * 1.6
            else:
                self.grp[key] += sgn * 1.6
            if not seeding:
                self.news.append({"t": ts, "key": key, "dir": int(sgn)})
                self.news = self.news[-30:]
        dec = math.exp(-dt / (6 * BAR_S))
        for k in self.burst:
            self.burst[k] *= dec
        self.momo = self.momo * self.phi ** f + np.sqrt(self.share) * np.sqrt(1 - self.phi ** (2 * f)) * rng.standard_normal(self.n)
        self._roll_regimes(f)
        # drift per regime
        reg = self.regime
        dev = (np.log(self.price) - self.anchor) / (self.sigma + 1e-12)
        drift = np.where(reg == 0, self.mu, np.where(reg == 1, -self.mu, np.where(reg == 2, -0.10 * np.clip(dev, -6, 6), 0.02 * self.momo)))
        vm = np.where(reg == 3, 0.45, 1.0) * self.session_mult(ts)
        # factor terms
        gvec = np.array([self.grp[g] for g in GROUPS])
        gvec = gvec.copy(); gvec[0] = self.risk
        macro_i = self.gload @ gvec * K_GROUP
        fxm = self.fx_e * K_FX_MACRO * (self.macro * 0.6 + self.risk * 0.8) / 1.0
        macro_i = np.where(self.is_fx, fxm, macro_i)
        cvec = np.array([self.ccy[c] for c in CURRENCIES])
        ccy_i = np.where(self.is_fx, cvec[np.clip(self.fx_b, 0, None)] - cvec[np.clip(self.fx_q, 0, None)], 0.0)
        bmul = np.ones(self.n)
        for g, v in self.burst.items():
            if v < .02:
                continue
            if g in CURRENCIES:
                j = CURRENCIES.index(g)
                bmul += v * ((self.fx_b == j) | (self.fx_q == j))
            else:
                bmul += v * 0.5 * (self.gload[:, GROUPS.index(g)] != 0)
        eps = rng.standard_normal(self.n)
        if self._no_drift:
            drift = drift * 0.0
        z = f * drift + self.vscale * (f * (self.momo + W_MACRO * macro_i + W_CCY * ccy_i) + sf * self.idio * eps)
        r = self.sigma * vm * bmul * z
        old = self.price
        new = old * np.exp(r)
        self.price = new
        self._accumulate(old, new, dt, r, vm * bmul, ts)
        return old, new

    def _accumulate(self, old, new, dt, r, vmul, ts):
        rng = self.rng
        self.fh = np.maximum(self.fh, np.maximum(old, new) * (1 + np.abs(rng.standard_normal(self.n)) * self.sigma * 0.15 * math.sqrt(dt / BAR_S)))
        self.fl = np.minimum(self.fl, np.minimum(old, new) * (1 - np.abs(rng.standard_normal(self.n)) * self.sigma * 0.15 * math.sqrt(dt / BAR_S)))
        f = dt / BAR_S
        v = self.basevol * f * vmul * np.exp(0.35 * rng.standard_normal(self.n)) * (1 + 1.5 * np.abs(r) / (self.sigma + 1e-12))
        imb = np.tanh(r / (self.sigma * math.sqrt(f) + 1e-12) * 0.55) * 0.22 + 0.04 * rng.standard_normal(self.n)
        bv = v * np.clip(0.5 + imb, 0.05, 0.95)
        self.fv += v; self.fbv += bv
        self.tick_signed += np.sign(new - old) * v
        self.fc = new

    def _close_bar(self, ts):
        rng = self.rng
        c = self.price.copy()
        for arr, val in ((self.O, self.fo), (self.H, np.maximum(self.fh, np.maximum(self.fo, c))), (self.Lo, np.minimum(self.fl, np.minimum(self.fo, c))),
                         (self.C, c), (self.V, self.fv), (self.BV, self.fbv), (self.SP, self._spread_now(ts)),
                         (self.tick_signed_hist, self.tick_signed)):
            arr[:, :-1] = arr[:, 1:]
            arr[:, -1] = val
        # live merge: replace closed bar with a real 1m bar if fresh
        if self._live_bars:
            for idx, (lts, o, h, l, cl, vv, bvv) in list(self._live_bars.items()):
                if ts - lts <= 150 and cl > 0:
                    self.O[idx, -1], self.H[idx, -1], self.Lo[idx, -1], self.C[idx, -1] = o, h, l, cl
                    if vv > 0:
                        self.V[idx, -1], self.BV[idx, -1] = vv, bvv
                    self.price[idx] = cl
                    self.anchor[idx] = math.log(cl)
            self._live_bars.clear()
        self.nbars = min(self.nbars + 1, CAP)
        self.fo = self.price.copy(); self.fh = self.price.copy(); self.fl = self.price.copy()
        self.fv = np.zeros(self.n); self.fbv = np.zeros(self.n); self.tick_signed = np.zeros(self.n)
        self.open_px = self.price.copy()

    def _spread_now(self, ts):
        vol_state = np.clip(self.session_mult(ts), .4, 2.0)
        return self.spread_bps * (1.5 / vol_state) ** 0.35

    # ----------------------------------------------------------------- API
    def advance(self, dt_total: float, sub: float = 2.0):
        """advance market time by dt_total seconds (sub-ticked)"""
        self._acc += dt_total
        while self._acc >= sub - 1e-9:
            dt = sub
            self._acc -= dt
            self.ts += dt
            old, new = self._step(dt, self.ts)
            self.t_in_bar += dt
            for cb in self.listeners:
                cb(old, new, self.ts)
            if self.t_in_bar >= BAR_S - 1e-9:
                self.t_in_bar -= BAR_S
                self._close_bar(self.ts)

    def _calibrate(self):
        """measure realised bar vol per instrument on a throw-away run so sigma means sigma"""
        st = self.rng.bit_generator.state
        snap = (self.price.copy(), self.regime.copy(), self.regime_left.copy(), self.momo.copy(), self.anchor.copy(),
                self.macro, self.risk, dict(self.ccy), dict(self.grp), dict(self.burst))
        ts = self.ts
        self._no_drift = True
        lp = [np.log(self.price)]
        for b in range(220):
            for _ in range(6):
                ts += 10.0
                self._step(10.0, ts, seeding=True)
            lp.append(np.log(self.price))
        R = np.diff(np.array(lp), axis=0)
        ratio = R.std(axis=0) / (self.sigma * 1.0)
        self.vscale = 1.0 / np.clip(ratio, .3, 6.0)
        self._no_drift = False
        (self.price, self.regime, self.regime_left, self.momo, self.anchor, self.macro, self.risk, self.ccy, self.grp, self.burst) = snap
        self.rng.bit_generator.state = st
        self.fo = self.price.copy(); self.fh = self.price.copy(); self.fl = self.price.copy()
        self.fv = np.zeros(self.n); self.fbv = np.zeros(self.n); self.tick_signed = np.zeros(self.n)

    def _seed_history(self):
        ts0 = self.ts
        self.ts = ts0 - SEED_BARS * BAR_S
        for _ in range(SEED_BARS):
            for _ in range(6):
                self.ts += 10.0
                self._step(10.0, self.ts, seeding=True)
            self._close_bar(self.ts)
        self.ts = ts0
        self.t_in_bar = 0.0
        self.news.clear()

    # ---- views
    def closes(self, L: int = 200, include_forming: bool = True) -> np.ndarray:
        c = self.C[:, -L:]
        if include_forming:
            c = np.concatenate([c[:, 1:], self.price[:, None]], axis=1)
        return c

    def bar_count(self) -> int:
        return self.nbars

    def apply_live_bar(self, sym_idx: int, ts: float, o, h, l, c, v=0.0, bv=0.0):
        self._live_bars[sym_idx] = (ts, o, h, l, c, v, bv)

    def summary(self) -> list[dict]:
        out = []
        prev = self.C[:, -30] if self.nbars > 30 else self.C[:, -2]
        for i in self.u:
            k = i.idx
            p = float(self.price[k])
            ch = (p / float(prev[k]) - 1.0) * 100 if prev[k] else 0.0
            out.append({"s": i.sym, "c": i.cls, "p": round(p, i.decimals), "ch": round(ch, 3),
                        "r": REGIMES[int(self.regime[k])]})
        return out

    def regime_name(self, idx: int) -> str:
        return REGIMES[int(self.regime[idx])]
