"""Microstructure module.

* Background thread polls Binance /api/v3/depth (20 levels, top-14 crypto, ~12 s each):
  book pressure, depth-tilt (bps/5), Cont-Kukanov-Stoikov OFI (EWMA .72/.28), live
  spread bps, taker-buy aggressor from klines.  Everything decays gracefully to
  neutral when unreachable / stale (>75 s).
* Trade-only estimators for everything else: Roll (1984) spread, Amihud (2002)
  illiquidity x1e9, tick-rule aggressor.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .universe import BINANCE_TOP14, UNIVERSE, SYM_INDEX

STALE_S = 75.0
POLL_S = 12.0
OFI_EWMA = (0.72, 0.28)      # (old, new)
DEPTH_URL = "https://api.binance.com/api/v3/depth"


# --------------------------------------------------------- trade-only estimators
def roll_spread_bps(closes: np.ndarray) -> np.ndarray:
    """Roll (1984): spread = 2*sqrt(-cov(dP_t, dP_t-1)); row-wise, in bps of price."""
    d = np.diff(closes, axis=1)
    a, b = d[:, 1:], d[:, :-1]
    cov = ((a - a.mean(axis=1, keepdims=True)) * (b - b.mean(axis=1, keepdims=True))).mean(axis=1)
    s = 2.0 * np.sqrt(np.maximum(-cov, 0.0))
    return s / np.maximum(closes[:, -1], 1e-12) * 1e4


def amihud_lambda(closes: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Amihud (2002) illiquidity x 1e9 : mean(|ret| / dollar volume)."""
    ret = np.abs(np.diff(np.log(np.maximum(closes, 1e-12)), axis=1))
    dv = np.maximum(closes[:, 1:] * volume[:, 1:], 1e-9)
    return (ret / dv).mean(axis=1) * 1e9


def tick_rule_imbalance(closes: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """tick rule: sign(dP) * V, zero-change inherits previous sign; returns signed share in [-1,1]."""
    d = np.sign(np.diff(closes, axis=1))
    for k in range(1, d.shape[1]):
        z = d[:, k] == 0
        d[z, k] = d[z, k - 1]
    v = volume[:, 1:]
    return (d * v).sum(axis=1) / np.maximum(v.sum(axis=1), 1e-12)


# ------------------------------------------------------------- depth features
def book_features(bids: list, asks: list) -> dict:
    """bids/asks: [[price, qty], ...] best first (20 levels)."""
    b = np.array([[float(p), float(q)] for p, q in bids], dtype=float)
    a = np.array([[float(p), float(q)] for p, q in asks], dtype=float)
    w = 1.0 / (1.0 + np.arange(len(b)))
    bq, aq = float((b[:, 1] * w).sum()), float((a[:, 1] * w[: len(a)]).sum())
    pressure = (bq - aq) / max(bq + aq, 1e-18)
    mid = 0.5 * (b[0, 0] + a[0, 0])
    spread_bps = (a[0, 0] - b[0, 0]) / mid * 1e4
    # depth tilt: liquidity inside 5 bps ... 25 bps of mid, signed, scaled by bps/5
    lo, hi = mid * (1 - 25e-4), mid * (1 + 25e-4)
    bd = float(b[b[:, 0] >= lo, 1].sum()); ad = float(a[a[:, 0] <= hi, 1].sum())
    tilt = (bd - ad) / max(bd + ad, 1e-18)
    return {"pressure": pressure, "tilt": tilt, "tilt_bps5": tilt * (25.0 / 5.0), "spread_bps": spread_bps,
            "bid": b[0, 0], "ask": a[0, 0], "bid_q": b[0, 1], "ask_q": a[0, 1], "mid": mid}


def ofi_step(prev: dict | None, cur: dict) -> float:
    """Cont-Kukanov-Stoikov order-flow imbalance between two top-of-book snapshots, size-normalised."""
    if prev is None:
        return 0.0
    e = 0.0
    e += cur["bid_q"] if cur["bid"] >= prev["bid"] else 0.0
    e -= prev["bid_q"] if cur["bid"] <= prev["bid"] else 0.0
    e -= cur["ask_q"] if cur["ask"] <= prev["ask"] else 0.0
    e += prev["ask_q"] if cur["ask"] >= prev["ask"] else 0.0
    norm = 0.5 * (cur["bid_q"] + cur["ask_q"] + prev["bid_q"] + prev["ask_q"]) + 1e-18
    return float(np.tanh(e / norm))


@dataclass
class MicroState:
    pressure: float = 0.0
    tilt: float = 0.0
    ofi: float = 0.0
    spread_bps: float = 0.0
    taker: float = 0.0          # taker-buy share - 0.5, *2
    at: float = -1e9
    last_book: dict | None = None


class MicroModule:
    def __init__(self, symbols: list[str] | None = None, clock=time.time):
        self.symbols = symbols or list(BINANCE_TOP14)
        self.state: dict[str, MicroState] = {s: MicroState() for s in self.symbols}
        self.clock = clock
        self.enabled = True
        self.reachable = False
        self.polls = 0
        self.errors = 0
        self.last_error = ""
        self._stop = threading.Event()
        self._th: threading.Thread | None = None

    # ---- ingestion (pure; used by the thread and by the tests)
    def ingest_book(self, sym: str, bids: list, asks: list, now: float | None = None):
        st = self.state.setdefault(sym, MicroState())
        f = book_features(bids, asks)
        raw = ofi_step(st.last_book, f)
        st.ofi = OFI_EWMA[0] * st.ofi + OFI_EWMA[1] * raw
        st.pressure, st.tilt, st.spread_bps = f["pressure"], f["tilt"], f["spread_bps"]
        st.last_book = f
        st.at = self.clock() if now is None else now

    def ingest_taker(self, sym: str, taker_buy_ratio: float):
        st = self.state.setdefault(sym, MicroState())
        st.taker = float(np.clip((taker_buy_ratio - 0.5) * 2, -1, 1))

    def age(self, sym: str, now: float | None = None) -> float:
        st = self.state.get(sym)
        return 1e9 if st is None else (self.clock() if now is None else now) - st.at

    def weight(self, sym: str, now: float | None = None) -> float:
        """1 while fresh, linear fade to 0 at STALE_S (graceful decay to neutral)"""
        a = self.age(sym, now)
        if a >= STALE_S:
            return 0.0
        return 1.0 if a <= 30 else max(0.0, 1.0 - (a - 30) / (STALE_S - 30))

    def features(self, sym: str, now: float | None = None) -> dict | None:
        st = self.state.get(sym)
        if st is None:
            return None
        w = self.weight(sym, now)
        if w <= 0:
            return None
        return {"pressure": st.pressure * w, "ofi": st.ofi * w, "tilt": st.tilt * w, "taker": st.taker * w,
                "spread_bps": st.spread_bps, "weight": w}

    # ---- thread
    def start(self):
        if self._th and self._th.is_alive():
            return
        self._stop.clear()
        self._th = threading.Thread(target=self._run, name="micro-depth", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        import httpx
        i = 0
        with httpx.Client(timeout=6.0) as cli:
            while not self._stop.is_set():
                if self.enabled and self.symbols:
                    sym = self.symbols[i % len(self.symbols)]
                    i += 1
                    try:
                        r = cli.get(DEPTH_URL, params={"symbol": UNIVERSE[SYM_INDEX[sym]].binance, "limit": 20})
                        r.raise_for_status()
                        j = r.json()
                        self.ingest_book(sym, j["bids"], j["asks"])
                        self.reachable = True
                        self.polls += 1
                    except Exception as e:      # noqa: BLE001
                        self.errors += 1
                        self.reachable = False
                        self.last_error = type(e).__name__
                # ~12 s per symbol cycle => spread the polls across the list
                self._stop.wait(POLL_S / max(1, min(len(self.symbols), 14)) * 1.0 if self.reachable else POLL_S)

    def snapshot(self, now: float | None = None) -> dict:
        out = {}
        for s, st in self.state.items():
            w = self.weight(s, now)
            out[s] = {"pressure": round(st.pressure * w, 3), "tilt_bps5": round(st.tilt * 5 * w, 3),
                      "ofi": round(st.ofi * w, 3), "spread_bps": round(st.spread_bps, 3) if w else None,
                      "taker": round(st.taker * w, 3), "age_s": round(min(self.age(s, now), 9999), 1), "weight": round(w, 2)}
        return {"reachable": self.reachable, "enabled": self.enabled, "polls": self.polls, "errors": self.errors,
                "last_error": self.last_error, "stale_s": STALE_S, "symbols": out}
