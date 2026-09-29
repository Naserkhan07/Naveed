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


def baseline(seat: str, t: Ticket, crowd: int = 0, bias: float = 0.0) -> tuple[float, str]:
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
    return float(sc + j + bias), why


METHOD = (
    "House method: every trade is a paper trade sized in R (1R = distance to the stop). Stop = 1.0 ATR, target = 2.2 ATR. "
    "A trade is worth taking only if the expected edge after spread/slippage is positive: P(win)*R:R - P(loss) > 0. "
    "Think like a professional: market structure, trend efficiency, momentum, volatility regime, liquidity/session, "
    "cross-asset correlation and currency strength, correlated exposure, costs. Be decisive and specific; never invent "
    "numbers that are not in the ticket. This is a simulation for research, not financial advice."
)

JSON_FMT = ('Reply ONLY with JSON: {"vote":"approve"|"reject","confidence":<0-100>,'
            '"thesis":"why this trade is or is not profitable, <=30 words","risk":"main thing that can go wrong, <=15 words",'
            '"reason":"one-line verdict, <=25 words"}.')


def ticket_facts(t: Ticket) -> dict:
    x = feats(t)
    return {"symbol": t.sym, "asset_class": t.cls, "direction": "LONG" if t.direction > 0 else "SHORT", "found_by": t.emitter,
            "regime": t.regime, "conviction": round(t.conviction, 2), "reward_to_risk": round(t.rr, 2),
            "entry": round(t.entry, 6), "stop": round(t.sl, 6), "target": round(t.tp, 6),
            "trend_alignment": round(x["trend"], 2), "momentum": round(x["mom"], 2), "efficiency": round(x["eff"], 2),
            "order_flow": round(x["flow"], 2), "liquidity_quality": round(x["liq"], 2), "vol_burst": round(x["vburst"], 2),
            "stretch": round(x["stretch"], 2), "peer_abs_corr": round(x["corr"], 2), "currency_strength": round(x["ccy"], 2),
            "cost_load_vs_limit": f"{x['cost']:.2f}/1.6"}


def dossier(votes: list[Vote]) -> str:
    if not votes:
        return "You are the first judge; nobody has ruled yet."
    return " | ".join(f"{v.seat} ({SEATS[v.seat]['role']}) {'APPROVED' if v.approve else 'REJECTED'} at {v.confidence}% - thesis: {v.thesis or v.reason}; risk: {v.risk or 'n/a'}"
                      for v in votes)


def judge_prompt(seat: str, t: Ticket, panel_so_far: list[Vote], notes: list[str] | None = None, record: str = "") -> list[dict]:
    info = SEATS[seat]
    sys_ = (f"You are {seat}, {info['role']} on a professional trading floor. {info['bio']} Your lens: {info['lens']}. {METHOD} "
            f"You sit in cabin {info['cabin']} of 5; each trade walks through all five cabins and the previous judges' notes are handed to you. "
            f"{JSON_FMT}")
    if notes:
        sys_ += " Lessons the team learned from recent results (apply them): " + " ".join(notes[-4:])
    user = (f"Ticket: {json.dumps(ticket_facts(t))}\nHandoff from earlier cabins: {dossier(panel_so_far)}\n"
            + (f"Floor track record: {record}\n" if record else "") + "Give your vote.")
    return [{"role": "system", "content": sys_}, {"role": "user", "content": user}]


def ceo_prompt(t: Ticket, notes: list[str] | None = None, record: str = "", crowd: int = 0) -> list[dict]:
    info = SEATS["NAVEED"]
    sys_ = (f"You are NAVEED, {info['role']}. The five-judge council split ({t.approvals}/5 approve) and the trade is on your desk. "
            f"Weigh the whole dossier (thesis, confidence and risk from every cabin), the floor's recent results and the {crowd} correlated tickets already open. "
            f"{METHOD} {JSON_FMT}")
    if notes:
        sys_ += " Team lessons: " + " ".join(notes[-4:])
    user = (f"Ticket: {json.dumps(ticket_facts(t))}\nCouncil dossier: {dossier(t.votes)}\n"
            + (f"Floor track record: {record}\n" if record else "") + "Rule: approve (entry gate) or reject (exit gate).")
    return [{"role": "system", "content": sys_}, {"role": "user", "content": user}]


def _num(v, lo=0, hi=100, default=0) -> int:
    try:
        return int(max(lo, min(hi, round(float(v)))))
    except (TypeError, ValueError):
        return default


def parse_vote(text: str) -> dict | None:
    """-> {approve, confidence, thesis, risk, reason} or None"""
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        j = json.loads(m.group(0)) if m else None
    except Exception:       # noqa: BLE001
        j = None
    if not isinstance(j, dict):
        return None
    v = str(j.get("vote", "")).lower()
    if v.startswith(("appr", "yes", "buy", "long", "enter", "accept")):
        ap = True
    elif v.startswith(("rej", "no", "den", "pass", "exit", "decl")):
        ap = False
    else:
        return None
    return {"approve": ap, "confidence": _num(j.get("confidence"), 0, 100, 60), "thesis": str(j.get("thesis", ""))[:260],
            "risk": str(j.get("risk", ""))[:160], "reason": str(j.get("reason", "") or j.get("thesis", ""))[:220]}


def enrich(seat: str, t: Ticket, approve: bool, score: float, why: str) -> tuple[int, str, str]:
    """offline confidence / thesis / risk so every stage hands the next one real information"""
    x = feats(t)
    conf = int(np.clip(50 + abs(score) * 90 + (6 if approve else 0), 8, 96))
    D = "long" if t.direction > 0 else "short"
    tgt = f"target {t.tp:.5g} is {t.rr:.2f}R against a {t.sl:.5g} stop"
    if approve:
        thesis = f"{D} {t.sym} has an edge here: {why.split(':')[0].lower()}; {tgt}."
    else:
        thesis = f"{D} {t.sym} lacks a clear edge: {why.split(':')[0].lower()}; {tgt} does not pay for the uncertainty."
    weak = {"ATLAS": f"trend alignment only {x['trend']:+.2f}", "QUANTA": f"efficiency {x['eff']:.2f} may not persist",
            "MERIDIAN": f"peer correlation {x['corr']:.2f} could decouple", "VOLTA": f"vol burst {x['vburst']:.2f} / liquidity {x['liq']:.2f}",
            "VECTOR": f"cost load {x['cost']:.2f}/1.6 and correlated exposure"}.get(seat, "regime change")
    return conf, thesis, weak


class JudgeService:
    def __init__(self, router: LLMRouter):
        self.router = router
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="judge")
        self.bias: dict[str, float] = {s: 0.0 for s in JUDGES + ["NAVEED"]}       # learned calibration (realised R)
        self.notes: dict[str, list[str]] = {s: [] for s in JUDGES + ["NAVEED"]}    # takeaways from the debate room
        self.record = ""                                                            # one-line track record for prompts
        self.learned = 0

    def llm_possible(self) -> bool:
        import os
        r = self.router
        if not r.enabled or r.force_offline:
            return False
        if any(c["provider"] != "auto" and c["base_url"] for c in r.cfg.values()):
            return True
        if r.free_enabled and r.breaker.allow():
            return True
        return r.hosted_enabled and any(os.environ.get(k) for k in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY", "OPENAI_API_KEY"))

    # ------------------------------------------------------------- learning
    def learn(self, t: Ticket):
        """called when a paper outcome is known: each judge that was on the wrong side becomes a little stricter / looser"""
        if t.r is None:
            return
        R = float(t.r)
        for v in t.votes:
            correct = (v.approve and R > 0) or ((not v.approve) and R <= 0)
            if not correct:
                step = 0.03 * min(2.0, abs(R) + 0.3)
                self.bias[v.seat] = float(np.clip(self.bias[v.seat] + (-step if v.approve else step), -0.3, 0.3))
        if t.ceo:
            correct = (t.ceo["vote"] == "approve" and R > 0) or (t.ceo["vote"] != "approve" and R <= 0)
            if not correct:
                step = 0.03 * min(2.0, abs(R) + 0.3)
                self.bias["NAVEED"] = float(np.clip(self.bias["NAVEED"] + (-step if t.ceo["vote"] == "approve" else step), -0.3, 0.3))
        self.learned += 1

    def offline_vote(self, seat: str, cabin: int, t: Ticket, crowd: int, suffix: str = "") -> Vote:
        score, why = baseline(seat, t, crowd, self.bias.get(seat, 0.0))
        conf, thesis, risk = enrich(seat, t, score > 0, score, why)
        return Vote(seat, cabin, score > 0, score, why + suffix, "offline:reasoning", 0, conf, thesis, risk)

    def add_note(self, seat: str, text: str):
        if seat in self.notes:
            self.notes[seat] = ([n for n in self.notes[seat] if n != text[:240]] + [text[:240]])[-6:]

    def review(self, seat: str, cabin: int, t: Ticket, crowd: int) -> Future | Vote:
        """returns a finished Vote (offline) or a Future[Vote] (LLM in a worker thread)"""
        score, why = baseline(seat, t, crowd, self.bias.get(seat, 0.0))
        ap = score > 0
        conf, thesis, risk = enrich(seat, t, ap, score, why)
        base = Vote(seat, cabin, ap, score, why, "offline:reasoning", 0, conf, thesis, risk)
        if not self.llm_possible():
            return base
        prior = list(t.votes)
        notes, rec = list(self.notes.get(seat, [])), self.record

        def work() -> Vote:
            t0 = time.time()
            text, label = self.router.complete(seat, judge_prompt(seat, t, prior, notes, rec), max_tokens=220)
            if text:
                pv = parse_vote(text)
                if pv:
                    return Vote(seat, cabin, pv["approve"], score, pv["reason"] or why, label, int((time.time() - t0) * 1000),
                                pv["confidence"], pv["thesis"] or thesis, pv["risk"] or risk)
            return Vote(seat, cabin, base.approve, score, why, "offline:reasoning", int((time.time() - t0) * 1000), conf, thesis, risk)

        return self.pool.submit(work)

    def ceo(self, t: Ticket, crowd: int) -> Future | dict:
        mean = float(np.mean([v.score for v in t.votes])) if t.votes else 0.0
        appr = t.approvals
        s = (0.9 * mean + 0.25 * (t.conviction - 0.7) + 0.20 * (t.rr - 1.7) - 0.03 * crowd + (0.12 if appr >= 4 else 0.0)
             + _jit(t.id, "NAVEED", 0.05) + self.bias.get("NAVEED", 0.0))
        approve = s > 0
        why = (f"{appr}/5 for; panel mean {mean:+.2f}, conviction {t.conviction:.2f}, R:R {t.rr:.2f}. {'Proceed' if approve else 'Stand down'}.")
        confs = [v.confidence for v in t.votes if v.approve == approve] or [55]
        thesis = (f"Council leaned {appr}-{5 - appr}; the case for {'taking' if approve else 'passing on'} {t.sym} rests on "
                  f"{max(t.votes, key=lambda v: abs(v.score)).seat}'s read: {max(t.votes, key=lambda v: abs(v.score)).reason[:90]}" if t.votes else why)
        base = {"seat": "NAVEED", "vote": "approve" if approve else "reject", "reason": why, "label": "offline:reasoning", "score": round(s, 3),
                "confidence": int(np.clip(np.mean(confs) * 0.9 + abs(s) * 30, 20, 95)), "thesis": thesis,
                "risk": "correlated exposure and regime change" if crowd else "regime change / slippage"}
        if not self.llm_possible():
            return base
        notes, rec = list(self.notes.get("NAVEED", [])), self.record

        def work() -> dict:
            text, label = self.router.complete("NAVEED", ceo_prompt(t, notes, rec, crowd), max_tokens=240)
            if text:
                pv = parse_vote(text)
                if pv:
                    return {"seat": "NAVEED", "vote": "approve" if pv["approve"] else "reject", "reason": pv["reason"] or why, "label": label,
                            "score": round(s, 3), "confidence": pv["confidence"], "thesis": pv["thesis"] or thesis, "risk": pv["risk"] or base["risk"]}
            return base

        return self.pool.submit(work)
