"""The 29 senses (glomeruli).  Vectorised over the whole universe.

 0-11  tape        trend up/down, momentum, stretch, breakout up/down, vol regime,
                   volume surge, efficiency, session, spread cost, vol burst
 12-20 deep stats  55-bar range position, ATR7/ATR14 expansion, candle-body conviction,
                   variance-ratio persistence, return autocorr, skew, kurtosis,
                   VWAP distance (ATR units), signed flow imbalance
 21-24 order book  L2 book pressure +-, OFI EWMA, aggressor/taker imbalance, Amihud liquidity quality
 25-28 correlation |rho| strongest peer, corr break, currency-strength spread, lead-lag edge
"""
from __future__ import annotations

import math

import numpy as np

from ..market.micro import MicroModule, amihud_lambda, roll_spread_bps, tick_rule_imbalance
from ..market.universe import UNIVERSE

N_SENSE = 29
SENSE_NAMES = [
    "trend_up", "trend_down", "momentum", "stretch", "breakout_up", "breakout_down", "vol_regime",
    "volume_surge", "efficiency", "session", "spread_cost", "vol_burst",
    "range_pos55", "atr_expansion", "body_conviction", "var_ratio", "autocorr", "skew", "kurtosis",
    "vwap_dist", "flow_imbalance",
    "book_pressure", "ofi_ewma", "aggressor", "liquidity_q",
    "peer_abs_rho", "corr_break", "ccy_strength", "lead_lag",
]
SLOPE_UNIT = 0.02           # slopes are measured in vol-units (sigma/bar) * 0.02 so the 120/60 gains bite
SPREAD_RATIO_SCALE = 26.0
SPREAD_HORIZON_BARS = 10.0  # spread compared against the ~600 s expected excursion


def _slope(y: np.ndarray, w: int) -> np.ndarray:
    seg = y[:, -w:]
    x = np.arange(w) - (w - 1) / 2.0
    return (seg - seg.mean(axis=1, keepdims=True)) @ x / (x @ x)


def _atr(H, L, C, n):
    pc = C[:, :-1]
    tr = np.maximum(H[:, 1:] - L[:, 1:], np.maximum(np.abs(H[:, 1:] - pc), np.abs(L[:, 1:] - pc)))
    return tr[:, -n:].mean(axis=1)


def compute(tape, corr, micro: MicroModule | None, now: float) -> tuple[np.ndarray, dict]:
    n = tape.n
    W = 120
    Cc, Hc, Lc, Oc = tape.C[:, -W:], tape.H[:, -W:], tape.Lo[:, -W:], tape.O[:, -W:]
    Vc, BVc = tape.V[:, -W:], tape.BV[:, -W:]
    px = tape.price
    C = np.concatenate([Cc[:, 1:], px[:, None]], axis=1)
    H = np.concatenate([Hc[:, 1:], np.maximum(tape.fh, px)[:, None]], axis=1)
    L = np.concatenate([Lc[:, 1:], np.minimum(tape.fl, px)[:, None]], axis=1)
    O = np.concatenate([Oc[:, 1:], tape.fo[:, None]], axis=1)
    V = np.concatenate([Vc[:, 1:], tape.fv[:, None]], axis=1)
    BV = np.concatenate([BVc[:, 1:], tape.fbv[:, None]], axis=1)
    lc = np.log(np.maximum(C, 1e-12))
    r = np.diff(lc, axis=1)
    sig = r[:, -55:].std(axis=1) + 1e-12
    atr14 = _atr(Hc, Lc, Cc, 14) + 1e-12          # closed bars only (forming bar has no full range yet)
    atr7 = _atr(Hc, Lc, Cc, 7) + 1e-12
    atr50 = _atr(Hc, Lc, Cc, 50) + 1e-12
    # --- trend composite  0.62*tanh(slope21*120) + 0.38*tanh(slope50*60)
    s21 = _slope(lc, 21) / sig * SLOPE_UNIT
    s50 = _slope(lc, 50) / sig * SLOPE_UNIT
    comp = 0.62 * np.tanh(s21 * 120) + 0.38 * np.tanh(s50 * 60)
    # --- efficiency (Kaufman, 20 bars)
    net = np.abs(lc[:, -1] - lc[:, -21])
    path = np.abs(np.diff(lc[:, -21:], axis=1)).sum(axis=1) + 1e-18
    eff = np.clip(net / path, 0, 1)
    S = np.zeros((n, N_SENSE))
    S[:, 0] = np.clip(comp, 0, 1)
    S[:, 1] = np.clip(-comp, 0, 1)
    S[:, 2] = np.tanh(r[:, -5:].sum(axis=1) / (sig * math.sqrt(5)) / 2.0)
    ema = C[:, -20:].mean(axis=1)
    S[:, 3] = np.tanh((px - ema) / (2 * atr14))
    hh = H[:, -21:-1].max(axis=1); ll = L[:, -21:-1].min(axis=1)
    S[:, 4] = np.clip((px - hh) / atr14 + 0.5, 0, 1) * (px > hh - 0.5 * atr14)
    S[:, 5] = np.clip((ll - px) / atr14 + 0.5, 0, 1) * (px < ll + 0.5 * atr14)
    S[:, 6] = np.clip(atr14 / atr50 / 2.0, 0, 1)
    vmean = V[:, -31:-1].mean(axis=1) + 1e-12
    S[:, 7] = np.clip(np.tanh(V[:, -2] / vmean - 1) * 0.5 + 0.5, 0, 1)   # last closed bar
    S[:, 8] = eff
    S[:, 9] = tape.session_quality(tape.ts)
    # spread cost
    spread_bps = tape.spread_bps * (1.5 / np.clip(tape.session_mult(tape.ts), .4, 2.0)) ** 0.35
    if micro is not None:
        for sym in micro.symbols:
            f = micro.features(sym, now)
            if f and f["spread_bps"] > 0:
                spread_bps[UNIVERSE_IDX[sym]] = f["spread_bps"]
    if tape.live_mode.startswith("LIVE"):
        live = roll_spread_bps(C[:, -56:])
        mask = np.array([i.idx in tape.live_idx for i in UNIVERSE]) if hasattr(tape, "live_idx") else np.zeros(n, bool)
        spread_bps = np.where(mask & (live > 0), live, spread_bps)
    spread_px = px * spread_bps / 1e4
    spread_ratio = spread_px / (SPREAD_HORIZON_BARS * atr14)
    S[:, 10] = np.clip(spread_ratio * SPREAD_RATIO_SCALE / 3.0, 0, 1)
    S[:, 11] = np.clip(np.tanh((H[:, -2] - L[:, -2]) / atr14 - 1) * 0.5 + 0.5, 0, 1)
    # --- deep stats
    hh55, ll55 = H[:, -55:].max(axis=1), L[:, -55:].min(axis=1)
    S[:, 12] = np.clip((px - ll55) / (hh55 - ll55 + 1e-12) * 2 - 1, -1, 1)
    S[:, 13] = np.tanh(atr7 / atr14 - 1)
    rng_ = H[:, -6:] - L[:, -6:] + 1e-12
    S[:, 14] = ((C[:, -6:] - O[:, -6:]) / rng_)[:, -5:].mean(axis=1)
    r1 = r[:, -55:]
    v1 = r1.var(axis=1) + 1e-18
    r4 = lc[:, -55:][:, 4:] - lc[:, -55:][:, :-4]
    vr = r4.var(axis=1) / (4 * v1)
    S[:, 15] = np.tanh((vr - 1) * 1.5)
    a, b = r1[:, 1:], r1[:, :-1]
    ac = ((a - a.mean(1, keepdims=True)) * (b - b.mean(1, keepdims=True))).mean(1) / v1
    S[:, 16] = np.clip(ac * 2, -1, 1)
    m3 = ((r1 - r1.mean(1, keepdims=True)) ** 3).mean(1) / (v1 ** 1.5)
    m4 = ((r1 - r1.mean(1, keepdims=True)) ** 4).mean(1) / (v1 ** 2) - 3
    S[:, 17] = np.tanh(m3 / 2)
    S[:, 18] = np.tanh(m4 / 4)
    typ = (H[:, -55:] + L[:, -55:] + C[:, -55:]) / 3
    vw = (typ * V[:, -55:]).sum(1) / (V[:, -55:].sum(1) + 1e-12)
    S[:, 19] = np.tanh((px - vw) / atr14)
    sell = V[:, -8:] - BV[:, -8:]
    S[:, 20] = (BV[:, -8:].sum(1) - sell.sum(1)) / (V[:, -8:].sum(1) + 1e-12)
    # --- order book / microstructure
    tick = tick_rule_imbalance(C[:, -31:], V[:, -31:])
    S[:, 23] = np.clip(tick * 1.5, -1, 1)
    am = amihud_lambda(C[:, -31:], V[:, -31:])
    am_long = amihud_lambda(C[:, -110:], V[:, -110:]) + 1e-30
    S[:, 24] = np.clip(1.5 - am / am_long, 0, 1)
    if micro is not None:
        for sym in micro.symbols:
            f = micro.features(sym, now)
            if not f:
                continue
            k = UNIVERSE_IDX[sym]
            S[k, 21] = f["pressure"]
            S[k, 22] = np.clip(f["ofi"] * 2, -1, 1)
            if abs(f["taker"]) > 0:
                S[k, 23] = np.clip(0.5 * S[k, 23] + 0.5 * f["taker"] * 1.5, -1, 1)
    # --- correlation
    t = corr.table
    if t.bars:
        S[:, 25] = np.where(np.abs(t.peer_rho) >= 0.72, np.abs(t.peer_rho), 0.0)
        S[:, 26] = np.clip(t.break_shift / 0.8, 0, 1)
        S[:, 27] = t.ccy_spread
        S[:, 28] = t.leadlag
    extras = {"atr": atr14, "atr7": atr7, "comp": comp, "eff": eff, "spread_ratio": spread_ratio,
              "spread_bps": spread_bps, "sig": sig, "px": px.copy()}
    return np.clip(S, -1, 1), extras


UNIVERSE_IDX = {i.sym: i.idx for i in UNIVERSE}
