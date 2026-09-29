"""Verdicts.  Each judge is a persona with a quantitative offline reasoner (always available, instant)
and an optional LLM vote (free keyless GPT -> hosted keys) that runs in a worker thread."""
from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from ..brain.senses import SENSE_NAMES
from ..llm.router import LLMRouter
from ..llm.seats import JUDGES, SEATS
from .models import Ticket, Vote

SI = {n: i for i, n in enumerate(SENSE_NAMES)}


def _jit(ticket_id: str, seat: str, amp: float = 0.17) -> float:
    h = int(hashlib.sha256(f"{ticket_id}:{seat}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return (h - 0.5) * 2 * amp


def feats(t: Ticket) -> dict:
    s = np.array(t.senses) if t.senses else np.zeros(29)
    d = t.direction
    g = lambda k: float(s[SI[k]])
    f = t.features
    return {
        "trend": float(np.clip(f.get("comp", 0.0) * d, -1, 1)), "mom": g("momentum") * d,
        "brk": (g("breakout_up") - g("breakout_down")) * d, "vr": g("var_ratio"), "ac": g("autocorr"),
        "eff": f.get("eff", g("efficiency")), "corr": g("peer_abs_rho"), "ccy": g("ccy_strength") * d,
        "lead": g("lead_lag") * d, "vol": g("vol_regime"), "flow": g("flow_imbalance") * d + 0.5 * g("aggressor") * d,
        "liq": g("liquidity_q"), "rr": t.rr, "cost": f.get("spread_ratio", 0.0) * 26.0, "risk": 0.0,
        "vburst": g("vol_burst"), "stretch": g("stretch") * d, "body": g("body_conviction") * d,
        "sess": g("session"), "conv": t.conviction, "kurt": g("kurtosis"), "skew": g("skew") * d,
    }


def baseline(seat: str, t: Ticket, crowd: int = 0) -> tuple[float, str]:
    """persona-weighted score in about [-1, 1] and a one-line reason"""
    x = feats(t)
    j = _jit(t.id, seat)
    D = "long" if t.direction > 0 else "short"
    if seat == "ATLAS":
        sc = 0.55 * x["trend"] + 0.30 * x["mom"] + 0.20 * x["brk"] + 0.15 * x["body"] - 0.50 - 0.20 * max(0, x["stretch"] - 0.6)
        why = f"Trend {x['trend']:+.2f} and momentum {x['mom']:+.2f} vs the {D}; structure {'supports' if sc > 0 else 'does not support'} it."
    elif seat == "QUANTA":
        sc = 0.45 * (x["eff"] - 0.35) * 2 + 0.25 * x["vr"] + 0.20 * x["ac"] + 0.10 * x["skew"] - 0.10 * max(0, x["kurt"] - 0.5) - 0.34
        why = f"Efficiency {x['eff']:.2f}, variance-ratio {x['vr']:+.2f}, autocorr {x['ac']:+.2f}: {'persistent' if sc > 0 else 'noisy'} edge."
    elif seat == "MERIDIAN":
        neutral = 0.12 if x["corr"] < 0.05 else 0.0
        sc = 0.35 * x["ccy"] + 0.30 * x["lead"] + 0.25 * (x["corr"] - 0.6 if x["corr"] > 0 else -0.05) + neutral + 0.15 * x["trend"] - 0.20
        why = f"Currency/basket strength {x['ccy']:+.2f}, lead-lag {x['lead']:+.2f}, peer |rho| {x['corr']:.2f}: cross-asset {'aligned' if sc > 0 else 'unconvinced'}."
    elif seat == "VOLTA":
        sc = 0.30 * x["flow"] + 0.25 * (x["liq"] - 0.4) + 0.20 * (0.55 - abs(x["vol"] - 0.5)) - 0.30 * x["vburst"] + 0.10 * x["trend"] - 0.08
        why = f"Flow {x['flow']:+.2f}, liquidity {x['liq']:.2f}, vol burst {x['vburst']:.2f}: conditions {'orderly' if sc > 0 else 'unfriendly'}."
    else:  # VECTOR
        sc = 0.55 * (x["rr"] - 1.6) + 0.35 * (1.0 - min(1.0, x["cost"] / 1.6)) - 0.12 * crowd + 0.25 * (x["conv"] - 0.7) - 0.24
        why = f"R:R {x['rr']:.2f}, cost load {x['cost']:.2f}/1.6, {crowd} correlated open: risk {'acceptable' if sc > 0 else 'too rich'}."
    return float(sc + j), why


CEO_SYSTEM = ("You are NAVEED, CEO of a paper-trading floor, ruling on a panel that split. Reply ONLY with JSON "
              '{"vote":"approve"|"reject","reason":"<=25 words"}.')


def judge_prompt(seat: str, t: Ticket, panel_so_far: list[Vote]) -> list[dict]:
    info = SEATS[seat]
    x = feats(t)
    facts = {"symbol": t.sym, "direction": "LONG" if t.direction > 0 else "SHORT", "emitter": t.emitter, "conviction": round(t.conviction, 2),
             "rr": round(t.rr, 2), "trend": round(x["trend"], 2), "efficiency": round(x["eff"], 2), "flow": round(x["flow"], 2),
             "peer_abs_rho": round(x["corr"], 2), "cost_load": round(x["cost"], 2)}
    sys_ = (f"You are judge {seat} on a paper-trading review panel; your lens is {info['lens']}. Reply ONLY with JSON "
            '{"vote":"approve"|"reject","reason":"<=25 words"}. This is a simulation.')
    prior = "; ".join(f"{v.seat}:{'A' if v.approve else 'R'}" for v in panel_so_far) or "none yet"
    return [{"role": "system", "content": sys_}, {"role": "user", "content": f"Ticket: {json.dumps(facts)}. Earlier judges: {prior}."}]


def parse_vote(text: str) -> tuple[bool, str] | None:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        j = json.loads(m.group(0)) if m else None
    except Exception:       # noqa: BLE001
        j = None
    if j and str(j.get("vote", "")).lower().startswith(("appr", "yes", "buy", "long", "enter")):
        return True, str(j.get("reason", ""))[:220]
    if j and str(j.get("vote", "")).lower().startswith(("rej", "no", "den", "pass", "exit")):
        return False, str(j.get("reason", ""))[:220]
    return None


class JudgeService:
    def __init__(self, router: LLMRouter):
        self.router = router
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="judge")

    def llm_possible(self) -> bool:
        import os
        r = self.router
        if not r.enabled or r.force_offline:
            return False
        if r.free_enabled and r.breaker.allow():
            return True
        return r.hosted_enabled and any(os.environ.get(k) for k in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY", "OPENAI_API_KEY"))

    def review(self, seat: str, cabin: int, t: Ticket, crowd: int) -> Future | Vote:
        """returns a finished Vote (offline) or a Future[Vote] (LLM in a worker thread)"""
        score, why = baseline(seat, t, crowd)
        base = Vote(seat, cabin, score > 0, score, why, "offline:reasoning")
        if not self.llm_possible():
            return base
        prior = list(t.votes)

        def work() -> Vote:
            t0 = time.time()
            text, label = self.router.complete(seat, judge_prompt(seat, t, prior), max_tokens=120)
            if text:
                pv = parse_vote(text)
                if pv:
                    # LLM vote leads; the quantitative reasoning stays as tie-break evidence
                    return Vote(seat, cabin, pv[0], score, pv[1] or why, label, int((time.time() - t0) * 1000))
            return Vote(seat, cabin, base.approve, score, why, "offline:reasoning", int((time.time() - t0) * 1000))

        return self.pool.submit(work)

    def ceo(self, t: Ticket, crowd: int) -> Future | dict:
        mean = float(np.mean([v.score for v in t.votes])) if t.votes else 0.0
        appr = t.approvals
        x = feats(t)
        s = 0.9 * mean + 0.25 * (t.conviction - 0.7) + 0.20 * (t.rr - 1.7) - 0.03 * crowd + (0.12 if appr >= 4 else 0.0) + _jit(t.id, "NAVEED", 0.05)
        approve = s > 0
        why = (f"{appr}/5 for; panel mean {mean:+.2f}, conviction {t.conviction:.2f}, R:R {t.rr:.2f}. "
               f"{'Proceed' if approve else 'Stand down'}.")
        base = {"seat": "NAVEED", "vote": "approve" if approve else "reject", "reason": why, "label": "offline:reasoning", "score": round(s, 3)}
        if not self.llm_possible():
            return base
        facts = {"symbol": t.sym, "dir": "LONG" if t.direction > 0 else "SHORT", "approvals": f"{appr}/5", "panel_mean": round(mean, 2),
                 "rr": round(t.rr, 2), "conviction": round(t.conviction, 2), "reasons": [f"{v.seat}:{v.reason[:60]}" for v in t.votes]}

        def work() -> dict:
            text, label = self.router.complete("NAVEED", [{"role": "system", "content": CEO_SYSTEM},
                                                          {"role": "user", "content": json.dumps(facts)}], max_tokens=120)
            if text:
                pv = parse_vote(text)
                if pv:
                    return {"seat": "NAVEED", "vote": "approve" if pv[0] else "reject", "reason": pv[1] or why, "label": label, "score": round(s, 3)}
            return base

        return self.pool.submit(work)
