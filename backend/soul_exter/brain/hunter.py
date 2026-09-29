"""Fly-brain market hunter + the scan funnel shared by every emitter.

Emitters:  (fly) mushroom-body STRIKE   (bloc) bloc-lag convergence   (break) corr-break
Funnel:    cooldown (sym 40 s / global 11 s) -> conviction >= .62 -> cost gate
           spread_ratio*26 <= 1.6 -> trend gate (eff >= .32 AND |trend| >= .30) -> R:R >= 1.6
           (entry +-0.12 ATR, SL 1.0 ATR, TP 2.2 ATR) -> correlated-risk gate (>= .85 vs an
           open same-direction ticket) -> pipe cap 9.
OPERATOR RULE: correlation trades only in the strong band |rho| >= 0.90; table older than
60 s blocks correlation trades.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..market.corr import BREAK_SHIFT, STALE_S, STRONG, CorrelationEngine
from ..market.universe import UNIVERSE
from . import senses as SN
from .fly import BASE_THR, FlyBrain, MBON_NAMES

SYM_COOLDOWN_S = 40.0
GLOBAL_COOLDOWN_S = 11.0
MIN_CONVICTION = 0.62
COST_GATE = 1.6
SPREAD_RATIO_SCALE = SN.SPREAD_RATIO_SCALE
MIN_EFF = 0.32
MIN_TREND = 0.30
ENTRY_OFF, SL_ATR, TP_ATR = 0.12, 1.0, 2.2
MIN_RR = 1.6
CORR_RISK = 0.85
PIPE_CAP = 9
STAGES = ["cooldown", "conviction", "cost", "trend", "rr", "corr_risk", "pipe_cap"]


@dataclass
class Signal:
    idx: int
    sym: str
    direction: int
    emitter: str
    conviction: float
    entry: float
    sl: float
    tp: float
    atr: float
    rr: float
    spread_ratio: float
    comp: float
    eff: float
    hunger: float
    thr: float
    ts: float
    kc_idx: list[int] = field(default_factory=list)
    senses: list[float] = field(default_factory=list)
    mb: list[float] = field(default_factory=list)
    info: dict = field(default_factory=dict)


def price_plan(px: float, atr: float, direction: int, spread_px: float) -> tuple[float, float, float, float]:
    """(entry, sl, tp, rr) - stop-entry beyond price by 0.12 ATR, SL/TP measured from price; half-spread cost"""
    entry = px + direction * ENTRY_OFF * atr
    sl = px - direction * SL_ATR * atr
    tp = px + direction * TP_ATR * atr
    risk = abs(entry - sl) + spread_px / 2
    reward = abs(tp - entry) - spread_px / 2
    return entry, sl, tp, reward / max(risk, 1e-18)


class Hunter:
    def __init__(self, brain: FlyBrain | None = None):
        self.brain = brain or FlyBrain()
        self.n = len(UNIVERSE)
        self.last_sym: dict[int, float] = {}
        self.last_global = -1e9
        self.state = "ROAM"
        self.watch: list[dict] = []
        self.focus_idx = 0
        self.focus: dict = {}
        self.last_out: dict | None = None
        self.last_extras: dict | None = None
        self.thr = BASE_THR
        self.strike_until = -1e9
        self.scans = 0
        self.funnel = self._fresh_funnel()

    @staticmethod
    def _fresh_funnel() -> dict:
        return {"scans": 0,
                "candidates": {"fly": 0, "bloc": 0, "break": 0},
                "emitted": {"fly": 0, "bloc": 0, "break": 0},
                "stages": {s: {"in": 0, "out": 0} for s in STAGES},
                "blocked": {s: 0 for s in STAGES},
                "corr_band_blocked": 0, "corr_stale_blocked": 0}

    # ------------------------------------------------------------------ scan
    def scan(self, tape, corr: CorrelationEngine, micro, now: float, sim_t: float,
             open_tickets: list[tuple[int, int]], pipe_count: int) -> list[Signal]:
        self.scans += 1
        F = self.funnel
        F["scans"] += 1
        sense, ex = SN.compute(tape, corr, micro, now)
        out = self.brain.forward(sense, ex)
        self.last_out, self.last_extras = out, ex
        hunger = out["hunger"]
        d = out["dir"]
        spread_ratio = ex["spread_ratio"]
        spread_pen = np.clip(spread_ratio * SPREAD_RATIO_SCALE / COST_GATE - 0.6, 0, 1) * 0.06
        best = float(hunger.max())
        thr_base = float(self.brain.threshold(best, 0.0))
        self.brain.decay_fatigue(1.0)
        thr_i = thr_base + spread_pen
        self.thr = thr_base
        order = np.argsort(-hunger)
        self.focus_idx = int(order[0])
        cands: list[Signal] = []
        cf = corr.table
        corr_ok = cf.bars > 0 and corr.fresh(now)
        # ---- (a) fly emitter
        strikers = [int(i) for i in order[:12] if hunger[i] > thr_i[i] and out["mb"][i, 0] >= out["mb"][i, 1]]
        for i in strikers:
            conv = float(np.clip(0.24 * min(1.5, hunger[i] / max(thr_i[i], 1e-6)) + 0.18 * out["strength"][i]
                                 + 0.18 * min(1.0, abs(ex["comp"][i]) / 0.8) + 0.16 * ex["eff"][i], 0, 1))
            cands.append(self._mk(i, int(d[i]), "fly", conv, ex, hunger[i], thr_i[i], out, sense, sim_t))
        # ---- (b)/(c) correlation finders (strong band only, fresh table only)
        if cf.bars > 0:
            for i in range(self.n):
                pr = float(cf.peer_rho[i])
                z = float(cf.resid_z[i])
                bs = float(cf.break_shift[i])
                wants_bloc = abs(z) >= 1.5 and abs(pr) >= 0.72
                wants_break = bs >= BREAK_SHIFT
                if not (wants_bloc or wants_break):
                    continue
                if abs(pr) < STRONG:
                    if abs(pr) >= 0.72:
                        F["corr_band_blocked"] += 1
                    continue
                if not corr_ok:
                    F["corr_stale_blocked"] += 1
                    continue
                if wants_bloc:
                    dirn = -1 if z > 0 else 1
                    conv = float(np.clip(0.50 + 0.10 * min(abs(z), 4) + 2.0 * (abs(pr) - STRONG) + 0.05 * abs(ex["comp"][i]), 0, 1))
                    s = self._mk(i, dirn, "bloc", conv, ex, hunger[i], thr_i[i], out, sense, sim_t)
                    s.info = {"peer": UNIVERSE[int(cf.peer[i])].sym, "rho": round(pr, 3), "z": round(z, 2)}
                    cands.append(s)
                if wants_break:
                    r5 = float(cf.peer_resid5[i])
                    if r5 == 0:
                        continue
                    dirn = 1 if r5 > 0 else -1
                    conv = float(np.clip(0.42 + 0.55 * bs + 0.10 * abs(ex["comp"][i]) + 0.08 * ex["eff"][i], 0, 1))
                    s = self._mk(i, dirn, "break", conv, ex, hunger[i], thr_i[i], out, sense, sim_t)
                    s.info = {"peer": UNIVERSE[int(cf.peer[i])].sym, "rho": round(pr, 3), "shift": round(bs, 2)}
                    cands.append(s)
        # ---- funnel
        emitted: list[Signal] = []
        watch: dict[int, list[str]] = {}
        cands.sort(key=lambda s: -s.conviction)
        for s in cands:
            F["candidates"][s.emitter] += 1
            ok, failed = self._funnel(s, sim_t, open_tickets, pipe_count + len(emitted), cf, ex)
            if ok:
                self.last_sym[s.idx] = sim_t
                self.last_global = sim_t
                F["emitted"][s.emitter] += 1
                emitted.append(s)
                self.brain.struck()
                self.strike_until = sim_t + 8.0
            elif failed in ("trend", "cost", "rr", "conviction"):
                watch.setdefault(s.idx, []).append(failed)
        # watcher list (near-threshold hunters that fail a gate: WAIT_FOR_SETUP)
        for i in order[:8]:
            i = int(i)
            if i in watch or (hunger[i] > 0.8 * thr_i[i] and i not in [e.idx for e in emitted]):
                miss = watch.get(i)
                if miss is None:
                    miss = []
                    if ex["eff"][i] < MIN_EFF:
                        miss.append("efficiency")
                    if abs(ex["comp"][i]) < MIN_TREND:
                        miss.append("trend")
                    if spread_ratio[i] * SPREAD_RATIO_SCALE > COST_GATE:
                        miss.append("cost")
                if miss:
                    watch[i] = miss
        self.watch = [{"s": UNIVERSE[i].sym, "h": round(float(hunger[i]), 2), "missing": m}
                      for i, m in list(watch.items())[:6]]
        if emitted or sim_t < self.strike_until:
            self.state = "STRIKE"
        elif self.watch:
            self.state = "WAIT_FOR_SETUP"
        else:
            self.state = "ROAM"
        fi = self.focus_idx
        self.focus = {"s": UNIVERSE[fi].sym, "hunger": float(hunger[fi]), "dir": int(d[fi]), "heading_deg": float(np.degrees(out["heading"][fi])),
                      "g": out["g"][fi].round(3).tolist(), "pn": out["pn"][fi].round(3).tolist(),
                      "kc": np.where(out["kc"][fi] > 0)[0].tolist(), "mb": out["mb"][fi].round(3).tolist()}
        return emitted

    # ---------------------------------------------------------------- helpers
    def _mk(self, i, dirn, emitter, conv, ex, h, thr, out, sense, sim_t) -> Signal:
        px = float(ex["px"][i])
        atr = float(ex["atr"][i])
        spread_px = px * float(ex["spread_bps"][i]) / 1e4
        entry, sl, tp, rr = price_plan(px, atr, dirn, spread_px)
        return Signal(idx=i, sym=UNIVERSE[i].sym, direction=dirn, emitter=emitter, conviction=conv, entry=entry, sl=sl,
                      tp=tp, atr=atr, rr=rr, spread_ratio=float(ex["spread_ratio"][i]), comp=float(ex["comp"][i]),
                      eff=float(ex["eff"][i]), hunger=float(h), thr=float(thr), ts=sim_t,
                      kc_idx=out["kc_idx"][i].tolist(), senses=sense[i].round(4).tolist(),
                      mb=out["mb"][i].round(3).tolist())

    def _funnel(self, s: Signal, sim_t: float, open_tickets, pipe_count, cf, ex) -> tuple[bool, str | None]:
        F = self.funnel

        def gate(name, ok):
            F["stages"][name]["in"] += 1
            if ok:
                F["stages"][name]["out"] += 1
            else:
                F["blocked"][name] += 1
            return ok

        if not gate("cooldown", sim_t - self.last_sym.get(s.idx, -1e9) >= SYM_COOLDOWN_S and sim_t - self.last_global >= GLOBAL_COOLDOWN_S):
            return False, "cooldown"
        if not gate("conviction", s.conviction >= MIN_CONVICTION):
            return False, "conviction"
        if not gate("cost", s.spread_ratio * SPREAD_RATIO_SCALE <= COST_GATE):
            return False, "cost"
        if not gate("trend", s.eff >= MIN_EFF and abs(s.comp) >= MIN_TREND):
            return False, "trend"
        if not gate("rr", s.rr >= MIN_RR):
            return False, "rr"
        risky = False
        if cf.bars > 0:
            for j, dj in open_tickets:
                if j == s.idx:
                    risky = True
                    break
                if cf.rho[s.idx, j] * s.direction * dj >= CORR_RISK:
                    risky = True
                    break
        if not gate("corr_risk", not risky):
            return False, "corr_risk"
        if not gate("pipe_cap", pipe_count < PIPE_CAP):
            return False, "pipe_cap"
        return True, None

    def snapshot(self) -> dict:
        f = self.funnel
        b = self.brain
        return {"state": self.state, "threshold": round(float(self.thr), 3), "fatigue": round(b.fatigue, 3),
                "dopamine": round(b.dopamine, 3), "baseline": round(b.baseline, 3), "updates": b.n_updates,
                "focus": self.focus, "watch": self.watch, "funnel": f,
                "mbon_names": MBON_NAMES, "constants": {
                    "cooldown_sym_s": SYM_COOLDOWN_S, "cooldown_global_s": GLOBAL_COOLDOWN_S,
                    "min_conviction": MIN_CONVICTION, "cost_gate": COST_GATE, "min_eff": MIN_EFF, "min_trend": MIN_TREND,
                    "min_rr": MIN_RR, "corr_risk": CORR_RISK, "pipe_cap": PIPE_CAP, "strong_band": STRONG}}
