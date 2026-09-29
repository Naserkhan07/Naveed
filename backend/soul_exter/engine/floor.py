"""FloorEngine — 20 Hz sim: market tape -> fly hunter -> ticket walkers -> 5 judges -> CEO -> gates,
paper-evaluated outcomes -> dopamine + playbook, ambient NPCs, debate chamber lessons."""
from __future__ import annotations

import math
import os
import random
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass, asdict

import numpy as np

from ..brain.fly import FlyBrain
from ..brain.hunter import Hunter, Signal
from ..core import layout as L
from ..core.navgrid import NavGrid, get_grid
from ..llm.router import LLMRouter
from ..llm.seats import COLORS, JUDGES, SEATS, resolve_seat
from ..market.corr import CorrelationEngine, rho_pct
from ..market.micro import MicroModule
from ..market.tape import Tape
from ..market.universe import UNIVERSE
from .judges import JudgeService
from .models import Ticket, Vote
from .walker import Walker

SIM_HZ = 20
PAPER_WINDOW_S = 600.0
FILL_WINDOW_S = 300.0
SEAT_DWELL_S = 4.0
HEAR_DWELL_S = 3.5
CEO_DWELL_S = 5.0
LLM_WAIT_S = 22.0            # virtual wall seconds to wait for an LLM verdict before falling back
DEBATE_PERIOD_S = 22.0
DEBATE_SPEAKERS = JUDGES + ["DROSOPHILA"]
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
BRAIN_PATH = os.path.join(DATA_DIR, "fly_brain.npz")


@dataclass
class Settings:
    speed: float = 1.0
    live: bool = True
    llm: bool = True
    free_gpt: bool = True
    ambient: int = 12
    ceo_doctrine: bool = False
    theme: str = "night"
    seed: int = 7

    def update(self, d: dict) -> None:
        for k, v in d.items():
            if not hasattr(self, k):
                continue
            cur = getattr(self, k)
            try:
                if isinstance(cur, bool):
                    v = bool(v)
                elif isinstance(cur, int):
                    v = int(v)
                elif isinstance(cur, float):
                    v = float(v)
                elif isinstance(cur, str):
                    v = str(v)
            except (TypeError, ValueError):
                continue
            if k == "speed":
                v = float(np.clip(v, 0.25, 32))
            if k == "ambient":
                v = int(np.clip(v, 0, 24))
            if k == "theme" and v not in ("day", "night"):
                continue
            setattr(self, k, v)


class FloorEngine:
    def __init__(self, seed: int = 7, router: LLMRouter | None = None, micro: MicroModule | None = None,
                 nav: NavGrid | None = None, persist: bool = False, start_ts: float | None = None):
        self.settings = Settings(seed=seed)
        self.rng = random.Random(seed)
        self.nav = nav or get_grid()
        self.tape = Tape(seed=seed, start_ts=start_ts)
        self.corr = CorrelationEngine()
        self.micro = micro or MicroModule()
        self.router = router or LLMRouter()
        self.judges = JudgeService(self.router)
        brain = FlyBrain(seed=11)
        self.persist = persist
        self.brain_load_msg = "fresh brain"
        if persist and os.path.exists(BRAIN_PATH):
            ok, msg = brain.load(BRAIN_PATH)
            self.brain_load_msg = "loaded saved brain" if ok else f"rejected saved brain: {msg}"
        self.hunter = Hunter(brain)
        self.clock = 0.0               # virtual wall seconds
        self.sim_t = 0.0
        self._scan_acc = 0.0
        self.tickets: dict[str, Ticket] = {}
        self.order: list[str] = []
        self.walkers: dict[str, Walker] = {}
        self.desks = L.desks()
        self.desk_busy: dict[int, str] = {}
        self.n_ticket = 0
        self.events: deque = deque(maxlen=120)
        self.lessons: deque = deque(maxlen=80)
        self.doctrine: list[dict] = []
        self.chats: dict[str, list[dict]] = {s: [] for s in SEATS}
        self.chatroom: deque = deque(maxlen=80)
        self.playbook: dict[str, dict] = {}
        self.stats = {"tickets": 0, "entry": 0, "exit": 0, "unanimous": 0, "ceo_rulings": 0, "ceo_approved": 0,
                      "wins": 0, "losses": 0, "timeouts": 0, "unfilled": 0, "sumR": 0.0,
                      "entered_R": 0.0, "entered_n": 0, "rejected_R": 0.0, "rejected_n": 0, "unanimous_R": 0.0, "unanimous_n": 0}
        self.pending_reviews: dict[str, tuple] = {}
        self.judge_state: dict[str, dict] = {s: {"state": "idle", "ticket": None} for s in JUDGES + ["NAVEED"]}
        self.thinking = {"seat": "DROSOPHILA", "until": 0.0}
        self.debate = {"speaker": None, "text": "", "until": -1.0, "kind": ""}
        self._debate_next = 6.0
        self._doctrine_next = 240.0
        self._speak_i = 0
        self.lock = threading.RLock()
        self.violations: list[str] = []
        self.paper_active: list[str] = []
        self.tape.listeners.append(self._on_tick)
        self.corr.update(self.tape, self.clock, force=True)
        self.npc_desks: list[int] = []
        self._spawn_npcs()
        self.micro.clock = lambda: self.clock

    # ---------------------------------------------------------------- helpers
    def log(self, kind: str, text: str, tid: str | None = None):
        self.events.append({"t": round(self.sim_t, 1), "kind": kind, "text": text, "ticket": tid})

    def set_settings(self, d: dict):
        with self.lock:
            self.settings.update(d)
            s = self.settings
            self.router.enabled = s.llm
            self.router.free_enabled = s.free_gpt
            self._sync_npcs()

    def think(self, seat: str, secs: float = 4.0):
        self.thinking = {"seat": seat, "until": self.clock + secs}

    # -------------------------------------------------------------------- NPCs
    def _spawn_npcs(self):
        free = list(range(48))
        self.rng.shuffle(free)
        self.npc_desks = sorted(free[:24])
        self._sync_npcs()

    def _sync_npcs(self):
        want = self.settings.ambient
        cur = [w for w in self.walkers.values() if w.kind == "npc"]
        for w in cur[want:]:
            self.desk_busy.pop(w.data.get("desk"), None)
            del self.walkers[w.id]
        have = len([w for w in self.walkers.values() if w.kind == "npc"])
        for k in range(have, want):
            d = self.npc_desks[k]
            desk = self.desks[d]
            w = Walker(f"npc{k:02d}", "npc", "", desk["seat"][0], desk["seat"][1], "#94a3b8", self.rng)
            w.data = {"desk": d, "face": math.pi}
            w.sitting = True
            w.stage = "npc_sit"
            w.timer = self.rng.uniform(4, 40)
            self.desk_busy[d] = w.id
            self.walkers[w.id] = w

    def _npc_update(self, w: Walker, dt: float):
        desk = self.desks[w.data["desk"]]
        if w.stage == "npc_sit":
            w.timer -= dt
            if w.timer <= 0:
                spots = ["lobby_center", "cabin_%d_outside" % self.rng.randint(1, 5), "vault_deep", "exec_outside", "debate_inside",
                         "concourse_lobby", "boulevard_s", "concourse_entry", "boulevard_n", "vault_inside"]
                dest = self.rng.choice(spots)
                r = self.nav.route([tuple(desk["seat"]), tuple(desk["stand"]), self.nav.wp[dest]])
                if r:
                    w.sitting = False
                    w.route(r)
                    w.stage = "npc_out"
                    w.data["dest"] = dest
                else:
                    w.timer = 10
        elif w.stage == "npc_out" and not w.moving:
            w.stage = "npc_dwell"
            w.timer = self.rng.uniform(3, 9)
        elif w.stage == "npc_dwell":
            w.timer -= dt
            if w.timer <= 0:
                r = self.nav.route([(w.x, w.z), tuple(desk["stand"]), tuple(desk["seat"])])
                if r:
                    w.route(r)
                    w.stage = "npc_back"
                else:
                    w.timer = 5
        elif w.stage == "npc_back" and not w.moving:
            w.sitting = True
            w.stage = "npc_sit"
            w.timer = self.rng.uniform(15, 60)
            w.x, w.z = desk["seat"]

    # ------------------------------------------------------------ paper trading
    def _on_tick(self, old: np.ndarray, new: np.ndarray, ts: float):
        if not self.paper_active:
            return
        done = []
        for tid in self.paper_active:
            t = self.tickets[tid]
            i = t.idx
            lo, hi = float(min(old[i], new[i])), float(max(old[i], new[i]))
            d = t.direction
            if t.paper == "pending":
                touched = hi >= t.entry if d > 0 else lo <= t.entry
                if touched:
                    t.paper, t.t_fill = "filled", self.sim_t
                elif self.sim_t - t.t0 > FILL_WINDOW_S:
                    self._resolve(t, "unfilled", 0.0)
                    done.append(tid)
                    continue
                else:
                    continue
            risk = abs(t.entry - t.sl)
            hit_sl = lo <= t.sl if d > 0 else hi >= t.sl
            hit_tp = hi >= t.tp if d > 0 else lo <= t.tp
            cost = float(self.tape.price[i]) * float(self.tape.spread_bps[i]) / 1e4 / max(risk, 1e-12)
            if hit_sl:                                  # conservative: stop first when both touched
                self._resolve(t, "sl", -1.0 - cost)
                done.append(tid)
            elif hit_tp:
                self._resolve(t, "tp", abs(t.tp - t.entry) / risk - cost)
                done.append(tid)
            elif self.sim_t - (t.t_fill or t.t0) >= PAPER_WINDOW_S:
                r = (float(new[i]) - t.entry) * d / risk - cost
                self._resolve(t, "timeout", float(np.clip(r, -1.2, 2.4)))
                done.append(tid)
        for tid in done:
            self.paper_active.remove(tid)

    def _resolve(self, t: Ticket, how: str, R: float):
        t.paper, t.r, t.resolved_t = how, R, self.sim_t
        S = self.stats
        if how == "unfilled":
            S["unfilled"] += 1
            self.log("paper", f"{t.id} {t.sym} never filled", t.id)
            return
        S["wins" if R > 0 else "losses"] += 1
        if how == "timeout":
            S["timeouts"] += 1
        S["sumR"] += R
        if t.verdict == "ENTRY":
            S["entered_R"] += R; S["entered_n"] += 1
        elif t.verdict == "EXIT":
            S["rejected_R"] += R; S["rejected_n"] += 1
        if t.verdict_path == "unanimous":
            S["unanimous_R"] += R; S["unanimous_n"] += 1
        # dopamine from realised R
        t.dopamine = round(self.hunter.brain.reward(np.array(t.kc_idx, dtype=int), R, 0), 3)
        key = f"{t.emitter}|{t.cls}|{'L' if t.direction > 0 else 'S'}|{t.regime}"
        b = self.playbook.setdefault(key, {"n": 0, "wins": 0, "sumR": 0.0})
        b["n"] += 1; b["wins"] += 1 if R > 0 else 0; b["sumR"] += R
        self.log("paper", f"{t.id} {t.sym} {how.upper()} {R:+.2f}R  dopamine {t.dopamine:+.2f}"
                 + ("  [ENTERED]" if t.verdict == "ENTRY" else ""), t.id)

    # ------------------------------------------------------------------ tickets
    def _open_tickets(self) -> list[tuple[int, int]]:
        return [(t.idx, t.direction) for t in self.tickets.values() if t.open_risk()]

    def _pick_desk(self) -> int | None:
        busy = set(self.desk_busy) | set(self.npc_desks)
        free = [d for d in self.desks if d["id"] not in busy]
        if not free:
            return None
        gx, gz = L.ENTRY_X, 29.0
        free.sort(key=lambda d: math.hypot(d["x"] - gx, d["z"] - gz))
        return self.rng.choice(free[:6])["id"]

    def _spawn_ticket(self, s: Signal):
        desk = self._pick_desk()
        if desk is None:
            return None
        self.n_ticket += 1
        tid = f"T{self.n_ticket:04d}"
        inst = UNIVERSE[s.idx]
        t = Ticket(id=tid, idx=s.idx, sym=s.sym, cls=inst.cls, direction=s.direction, emitter=s.emitter,
                   conviction=s.conviction, entry=s.entry, sl=s.sl, tp=s.tp, atr=s.atr, rr=s.rr, t0=self.sim_t, desk=desk,
                   info=s.info, kc_idx=s.kc_idx, senses=s.senses, mb=s.mb, regime=self.tape.regime_name(s.idx),
                   features={"comp": round(s.comp, 3), "eff": round(s.eff, 3), "spread_ratio": round(s.spread_ratio, 4),
                             "hunger": round(s.hunger, 3), "thr": round(s.thr, 3)})
        cf = self.corr.table
        if cf.bars:
            mx = max([float(cf.rho[t.idx, o.idx]) * t.direction * o.direction for o in self.tickets.values() if o.open_risk()] or [0.0])
            t.features["max_open_rho"] = round(mx, 3)
        if s.emitter != "fly":
            t.features["corr_age_s"] = round(self.clock - cf.at, 1)
        self.tickets[tid] = t
        self.order.append(tid)
        self.desk_busy[desk] = tid
        self.paper_active.append(tid)
        self.stats["tickets"] += 1
        label = f"{'LONG' if s.direction > 0 else 'SHORT'} {s.sym}"
        w = Walker(f"w_{tid}", "ticket", label, *self.nav.wp["entry_outside"], COLORS["DROSOPHILA"], self.rng)
        w.ticket = tid
        w.stage = "enter"
        r = self.nav.route(["entry_outside", "entry_inside", f"desk_{desk}_stand", f"desk_{desk}_seat"])
        assert r, "no route to desk"
        w.route(r)
        t.walker_id = w.id
        t.status, t.stage = "to_desk", "enter"
        t.trace.append(("enter", round(self.sim_t, 1)))
        self.walkers[w.id] = w
        self.think("DROSOPHILA", 3.0)
        self.log("ticket", f"{tid} {label} via {s.emitter.upper()} conv {s.conviction:.2f} R:R {s.rr:.2f} -> desk {desk}", tid)
        while len(self.order) > 400:
            old = self.order.pop(0)
            if self.tickets[old].finished and self.tickets[old].paper not in ("pending", "filled"):
                del self.tickets[old]
            else:
                self.order.insert(0, old)
                break
        return t

    def _crowd(self, t: Ticket) -> int:
        cf = self.corr.table
        if cf.bars == 0:
            return 0
        n = 0
        for o in self.tickets.values():
            if o is t or not o.open_risk():
                continue
            if cf.rho[t.idx, o.idx] * t.direction * o.direction >= 0.6:
                n += 1
        return n

    def _to_cabin(self, w: Walker, t: Ticket, i: int):
        names = [(w.x, w.z), f"cabin_{i}_outside", f"cabin_{i}_door", f"cabin_{i}_hear"]
        r = self.nav.route(names)
        assert r, f"no route to cabin {i}"
        w.sitting = False
        w.route(r)
        w.stage, t.stage, t.cabin, t.status = f"to_cabin_{i}", f"to_cabin_{i}", i, "review"
        t.trace.append((f"to_cabin_{i}", round(self.sim_t, 1)))

    def _leave_via(self, w: Walker, t: Ticket, gate: str, via: list[str]):
        r = self.nav.route([(w.x, w.z)] + via + [f"{gate}_inside", f"{gate}_outside"])
        assert r, "no route to gate"
        w.route(r)
        w.stage, t.stage = f"leave_{gate}", f"leave_{gate}"
        t.trace.append((f"leave_{gate}", round(self.sim_t, 1)))

    def _ticket_update(self, w: Walker, dt: float):
        t = self.tickets.get(w.ticket)
        if t is None:
            w.gone = True
            return
        st = w.stage
        if st == "enter":
            if not w.moving:
                w.sitting, w.data["face"] = True, math.pi
                w.x, w.z = self.desks[t.desk]["seat"]
                w.stage, w.timer, t.stage, t.status = "seated", SEAT_DWELL_S, "seated", "seated"
                t.trace.append(("seated", round(self.sim_t, 1)))
        elif st == "seated":
            w.timer -= dt
            if w.timer <= 0:
                self._to_cabin(w, t, 1)
        elif st.startswith("to_cabin_"):
            if not w.moving:
                i = t.cabin
                seat = JUDGES[i - 1]
                w.data["face"] = math.pi
                w.h = math.pi
                w.stage = f"hearing_{i}"
                t.stage = f"hearing_{i}"
                t.trace.append((f"hearing_{i}", round(self.sim_t, 1)))
                w.timer = HEAR_DWELL_S
                w.data["wait0"] = self.clock
                res = self.judges.review(seat, i, t, self._crowd(t))
                self.pending_reviews[w.id] = (res,)
                self.judge_state[seat] = {"state": "hearing", "ticket": t.id}
                self.think(seat, 6.0)
        elif st.startswith("hearing_") and st != "hearing_exec":
            i = t.cabin
            seat = JUDGES[i - 1]
            w.timer -= dt
            res = self.pending_reviews[w.id][0]
            self.think(seat, 1.0)
            vote = None
            if isinstance(res, Vote):
                vote = res
            elif isinstance(res, Future):
                if res.done():
                    try:
                        vote = res.result()
                    except Exception:       # noqa: BLE001
                        vote = None
                        res = None
                elif self.clock - w.data["wait0"] > LLM_WAIT_S:
                    from .judges import baseline
                    sc, why = baseline(seat, t, self._crowd(t))
                    vote = Vote(seat, i, sc > 0, sc, why + " (LLM timeout)", "offline:reasoning")
            if vote is None and res is None:
                from .judges import baseline
                sc, why = baseline(seat, t, 0)
                vote = Vote(seat, i, sc > 0, sc, why, "offline:reasoning")
            if vote is not None and w.timer <= 0:
                self.pending_reviews.pop(w.id, None)
                t.votes.append(vote)
                w.color = COLORS[seat]
                self.judge_state[seat] = {"state": "idle", "ticket": None}
                self.log("vote", f"{seat} {'APPROVES' if vote.approve else 'REJECTS'} {t.id} {t.sym}: {vote.reason[:90]}", t.id)
                if i < 5:
                    self._to_cabin(w, t, i + 1)
                else:
                    self._after_panel(w, t)
        elif st == "hearing_exec":
            w.timer -= dt
            self.think("NAVEED", 1.0)
            res = self.pending_reviews[w.id][0]
            out = None
            if isinstance(res, dict):
                out = res
            elif res.done():
                out = res.result()
            elif self.clock - w.data["wait0"] > LLM_WAIT_S:
                out = {"seat": "NAVEED", "vote": "reject", "reason": "LLM timeout — stand down.", "label": "offline:reasoning", "score": -1}
            if out is not None and w.timer <= 0:
                self.pending_reviews.pop(w.id, None)
                t.ceo = out
                self.stats["ceo_rulings"] += 1
                ok = out["vote"] == "approve"
                self.judge_state["NAVEED"] = {"state": "idle", "ticket": None}
                w.color = COLORS["NAVEED"]
                self.log("ceo", f"NAVEED {'APPROVES' if ok else 'REJECTS'} {t.id} {t.sym}: {out['reason'][:100]}", t.id)
                if ok:
                    self.stats["ceo_approved"] += 1
                    self._finish_verdict(w, t, "ENTRY", "split->CEO", ["exec_door", "exec_outside", "concourse_lobby"])
                else:
                    self._finish_verdict(w, t, "EXIT", "split->CEO", ["exec_door", "exec_outside", "concourse_lobby"])
        elif st == "to_exec":
            if not w.moving:
                w.stage, t.stage, t.status = "hearing_exec", "hearing_exec", "exec"
                t.trace.append(("hearing_exec", round(self.sim_t, 1)))
                w.timer = CEO_DWELL_S
                w.data["wait0"] = self.clock
                w.data["face"] = math.pi / 2
                self.pending_reviews[w.id] = (self.judges.ceo(t, self._crowd(t)),)
                self.judge_state["NAVEED"] = {"state": "ruling", "ticket": t.id}
                self.think("NAVEED", 6.0)
        elif st.startswith("leave_"):
            if not w.moving:
                w.gone, w.fade = True, 1.0
                t.finished = True
                t.status = "entered" if t.verdict == "ENTRY" else "exited"
                t.trace.append(("done", round(self.sim_t, 1)))
                self.desk_busy.pop(t.desk, None)
                self.log("gate", f"{t.id} {t.sym} leaves through the {'ENTRY' if t.verdict == 'ENTRY' else 'EXIT'} gate", t.id)

    def _after_panel(self, w: Walker, t: Ticket):
        n = t.approvals
        if n == 5:
            self.stats["unanimous"] += 1
            self._finish_verdict(w, t, "ENTRY", "unanimous", ["cabin_5_door", "cabin_5_outside"])
        elif n >= 3:
            r = self.nav.route([(w.x, w.z), "cabin_5_door", "cabin_5_outside", "concourse_entry", "exec_outside", "exec_door", "exec_hear"])
            assert r, "no route to exec"
            w.route(r)
            w.stage, t.stage, t.status = "to_exec", "to_exec", "exec"
            t.trace.append(("to_exec", round(self.sim_t, 1)))
            self.log("panel", f"{t.id} {t.sym} split {n}/5 -> executive chamber", t.id)
        else:
            self._finish_verdict(w, t, "EXIT", "rejected", ["cabin_5_door", "cabin_5_outside"])

    def _finish_verdict(self, w: Walker, t: Ticket, verdict: str, path: str, via: list[str]):
        t.verdict, t.verdict_path = verdict, path
        self.stats["entry" if verdict == "ENTRY" else "exit"] += 1
        gate = "entry" if verdict == "ENTRY" else "exit"
        self.log("verdict", f"{t.id} {t.sym} {t.approvals}/5 -> {verdict} GATE ({path})", t.id)
        self._leave_via(w, t, gate, via)

    # ------------------------------------------------------------------ scanning
    def _scan(self):
        open_t = self._open_tickets()
        sigs = self.hunter.scan(self.tape, self.corr, self.micro, self.clock, self.sim_t, open_t, len(open_t))
        for s in sigs:
            self._spawn_ticket(s)

    # -------------------------------------------------------------- debate room
    def _bucket_lessons(self) -> list[tuple[str, str]]:
        out = []
        for k, b in self.playbook.items():
            if b["n"] >= 3:
                em, cl, dr, rg = k.split("|")
                out.append((k, f"{em} {cl} {'longs' if dr == 'L' else 'shorts'} in {rg} regimes: {b['n']} paper trades, "
                               f"win {100 * b['wins'] / b['n']:.0f}%, expectancy {b['sumR'] / b['n']:+.2f}R."))
        return out

    def _make_lesson(self) -> tuple[str, str, str]:
        S = self.stats
        speaker = DEBATE_SPEAKERS[self._speak_i % len(DEBATE_SPEAKERS)]
        self._speak_i += 1
        lens = SEATS[speaker]["lens"]
        F = self.hunter.funnel
        options: list[tuple[str, str]] = []
        for k, txt in sorted(self._bucket_lessons(), key=lambda kv: -abs(self.playbook[kv[0]]["sumR"]))[:4]:
            b = self.playbook[k]
            e = b["sumR"] / b["n"]
            options.append(("playbook", f"{txt} {'Lean into it.' if e > 0.15 else ('Fade or skip it.' if e < -0.15 else 'No edge yet — keep sampling.')}"))
        if S["entered_n"] >= 2 and S["rejected_n"] >= 2:
            ee, rr_ = S["entered_R"] / S["entered_n"], S["rejected_R"] / S["rejected_n"]
            options.append(("council", f"Council check — entered tickets {ee:+.2f}R over {S['entered_n']} vs rejected {rr_:+.2f}R over {S['rejected_n']}: "
                                       f"{'the panel is adding value' if ee > rr_ else 'the panel is not beating the raw hunter yet'}."))
        if F["scans"] > 5:
            tight = max(F["blocked"].items(), key=lambda kv: kv[1])
            options.append(("funnel", f"The tightest gate is '{tight[0]}' with {tight[1]} candidates stopped in {F['scans']} scans; "
                                      f"{sum(F['emitted'].values())} tickets got through."))
        b = self.hunter.brain
        options.append(("brain", f"Dopamine trace {b.dopamine:+.2f} after {b.n_updates} outcome updates; the mushroom body is "
                                 f"{'reinforcing recent attacks' if b.dopamine > 0.05 else ('suppressing recent attacks' if b.dopamine < -0.05 else 'sitting near baseline')}."))
        n_open = len([t for t in self.tickets.values() if t.open_risk()])
        options.append(("floor", f"{n_open} tickets in the pipe of 9; brain state {self.hunter.state}."))
        kind, text = options[(self._speak_i * 7 + int(self.sim_t)) % len(options)]
        return speaker, kind, f"[{lens.split(':')[0]}] {text}"

    def _debate_update(self):
        if self.sim_t >= self._debate_next:
            self._debate_next = self.sim_t + DEBATE_PERIOD_S
            speaker, kind, text = self._make_lesson()
            self.lessons.append({"t": round(self.sim_t, 1), "seat": speaker, "kind": kind, "text": text})
            self.debate = {"speaker": speaker, "text": text, "until": self.sim_t + 14.0, "kind": kind}
            self.log("lesson", f"{speaker}: {text[:110]}")
        if self.settings.ceo_doctrine and self.sim_t >= self._doctrine_next:
            self._doctrine_next = self.sim_t + 240.0
            pb = sorted(((k, b) for k, b in self.playbook.items() if b["n"] >= 3), key=lambda kv: -kv[1]["sumR"] / kv[1]["n"])
            if pb:
                best, worst = pb[0], pb[-1]
                text = (f"Doctrine #{len(self.doctrine) + 1}: favour {best[0].replace('|', ' / ')} ({best[1]['sumR'] / best[1]['n']:+.2f}R); "
                        f"avoid {worst[0].replace('|', ' / ')} ({worst[1]['sumR'] / worst[1]['n']:+.2f}R).")
                self.doctrine.append({"t": round(self.sim_t, 1), "text": text})
                self.log("doctrine", text)

    # ------------------------------------------------------------------- main step
    def step(self, dt_wall: float):
        with self.lock:
            self.clock += dt_wall
            dt = dt_wall * self.settings.speed
            left = dt
            while left > 1e-9:
                h = min(left, 0.25)
                left -= h
                self.sim_t += h
                self.tape.advance(h)
                self.corr.update(self.tape, self.clock)
                self._scan_acc += h
                while self._scan_acc >= 1.0:
                    self._scan_acc -= 1.0
                    self._scan()
                for w in list(self.walkers.values()):
                    if w.gone:
                        w.fade -= h
                        if w.fade <= 0:
                            del self.walkers[w.id]
                        continue
                    w.step(h)
                    if w.kind == "npc":
                        self._npc_update(w, h)
                    else:
                        self._ticket_update(w, h)
                self._debate_update()
            if self.persist and int(self.clock) % 120 == 0 and int(self.clock) != getattr(self, "_saved", -1) and self.hunter.brain.n_updates:
                self._saved = int(self.clock)
                self.save_brain()

    def save_brain(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.hunter.brain.save(BRAIN_PATH)

    # ------------------------------------------------------------------ chat
    def chat(self, seat_id, question: str, history: list[dict] | None = None, context: str | None = None) -> dict:
        seat = resolve_seat(seat_id)
        self.think(seat, 8.0)
        hist = history if history is not None else self.chats[seat]
        rep = self.router.chat(seat, question, hist, context)
        self.chats[seat].append({"role": "user", "content": question})
        self.chats[seat].append({"role": "assistant", "content": rep.text, "label": rep.label})
        del self.chats[seat][:-60]
        return {"seat": seat, "answer": rep.text, "label": rep.label, "ms": rep.ms, "color": COLORS[seat]}

    def trade_context(self, t: Ticket) -> str:
        return (f"Ticket {t.id}: {'LONG' if t.direction > 0 else 'SHORT'} {t.sym} via {t.emitter}, conviction {t.conviction:.2f}, "
                f"entry {t.entry:.5g} SL {t.sl:.5g} TP {t.tp:.5g} R:R {t.rr:.2f}, status {t.status}, votes "
                + ", ".join(f"{v.seat}:{'A' if v.approve else 'R'}" for v in t.votes)
                + (f", CEO {t.ceo['vote']}" if t.ceo else "") + f", paper {t.paper}" + (f" {t.r:+.2f}R" if t.r is not None else ""))

    # ---------------------------------------------------------------- snapshots
    def frame(self) -> dict:
        with self.lock:
            thinking = self.thinking["seat"] if self.clock < self.thinking["until"] else "DROSOPHILA"
            ws = [w.pose() for w in self.walkers.values()]
            return {"t": round(self.clock, 2), "sim": round(self.sim_t, 1), "speed": self.settings.speed, "walkers": ws,
                    "judges": self.judge_state, "thinking": {"seat": thinking, "color": COLORS[thinking]},
                    "debate": {"speaker": self.debate["speaker"] if self.sim_t < self.debate["until"] else None,
                               "text": self.debate["text"] if self.sim_t < self.debate["until"] else ""},
                    "brain_state": self.hunter.state}

    def orders(self, n: int = 60) -> list[dict]:
        with self.lock:
            return [self.tickets[i].card() for i in reversed(self.order[-n:]) if i in self.tickets]

    def council_stats(self) -> dict:
        S = self.stats
        avg = lambda a, b: round(S[a] / S[b], 3) if S[b] else None
        return {"entered": {"n": S["entered_n"], "avgR": avg("entered_R", "entered_n")},
                "rejected": {"n": S["rejected_n"], "avgR": avg("rejected_R", "rejected_n")},
                "unanimous": {"n": S["unanimous_n"], "avgR": avg("unanimous_R", "unanimous_n")}}

    def state(self) -> dict:
        with self.lock:
            S = self.stats
            n_res = S["wins"] + S["losses"]
            return {"time": {"clock": round(self.clock, 1), "sim": round(self.sim_t, 1), "utc": self.tape.ts, "bars": self.tape.nbars},
                    "settings": asdict(self.settings), "mode": self.tape.live_mode, "live_n": self.tape.live_n,
                    "stats": {**S, "winrate": round(S["wins"] / n_res, 3) if n_res else None,
                              "in_pipe": len([t for t in self.tickets.values() if t.open_risk()])},
                    "council": self.council_stats(), "brain_state": self.hunter.state, "brain_msg": self.brain_load_msg,
                    "playbook": {k: {**v, "avgR": round(v["sumR"] / v["n"], 3)} for k, v in sorted(self.playbook.items(), key=lambda kv: -kv[1]["n"])[:24]},
                    "lessons": list(self.lessons)[-12:], "doctrine": self.doctrine[-4:], "events": list(self.events)[-40:],
                    "chatroom": list(self.chatroom)[-30:], "llm": self.router.status(), "orders": self.orders(30),
                    "walkers": len(self.walkers)}

    def fly(self) -> dict:
        with self.lock:
            snap = self.hunter.snapshot()
            snap["correlation"] = self.corr.snapshot(self.clock)
            snap["microstructure"] = self.micro.snapshot(self.clock)
            snap["mode"] = self.tape.live_mode
            return snap

    def seats(self) -> list[dict]:
        out = []
        for name, s in SEATS.items():
            js = self.judge_state.get(name, {"state": "idle", "ticket": None})
            out.append({"id": name, "cabin": s["cabin"], "persona": s["persona"], "lens": s["lens"], "color": COLORS[name],
                        "state": js["state"], "ticket": js["ticket"], "label": self.router.last_label,
                        "messages": len(self.chats[name]) // 2})
        return out
