"""Smoke test:  python backend/tests/smoke_engine.py N S   (N wall-seconds x S speed, default 30 8)

Runs the whole floor headless at 20 Hz for N seconds at speed S and verifies
  * walk order   (entry -> desk -> cabin 1..5 in order -> [exec] -> entry/exit gate, verdict rules)
  * navmesh safety (every walker on true geometry every tick, no teleports)
  * scan funnel  (stage counters consistent, cooldowns, pipe cap 9, corr-band rule, corr-risk gate)
Exit code 0 = clean.
"""
from __future__ import annotations

import math
import os
import sys
import time

os.environ.setdefault("SOUL_OFFLINE", "1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from soul_exter.core import layout as L                      # noqa: E402
from soul_exter.core.navgrid import get_grid                 # noqa: E402
from soul_exter.engine.floor import FloorEngine              # noqa: E402
from soul_exter.brain.hunter import (GLOBAL_COOLDOWN_S, PIPE_CAP, STAGES, SYM_COOLDOWN_S)  # noqa: E402


def main(n_sec: float, speed: float, seed: int = 7) -> int:
    t_start = time.time()
    problems: list[str] = []
    nav = get_grid()

    # ---- static: layout + reachability -----------------------------------------------------
    lay = L.layout()
    if lay["hall"] != [-46.0, -28.6, 46.0, 32.6] or len(lay["desks"]) != 48:
        problems.append("layout: hall/desk count wrong")
    bad = nav.check_waypoints()
    if bad:
        problems.append(f"waypoints not walkable: {bad[:6]}")
    unreachable = []
    for k in nav.wp:
        if nav.route(["entry_outside", k]) is None:
            unreachable.append(k)
    if unreachable:
        problems.append(f"A* unreachable from entry_outside: {unreachable[:6]}")
    print(f"[static] waypoints={len(nav.wp)} walkable-bad={len(bad)} unreachable={len(unreachable)}")

    # ---- dynamic ----------------------------------------------------------------------------
    eng = FloorEngine(seed=seed)
    eng.set_settings({"speed": speed})
    eng.router.force_offline = True
    ticks = int(n_sec * 20)
    last: dict[str, tuple[float, float]] = {}
    off_grid = teleports = 0
    max_pipe = 0
    for k in range(ticks):
        eng.step(0.05)
        max_pipe = max(max_pipe, len([t for t in eng.tickets.values() if t.open_risk()]))
        maxstep = 2.4 * 0.05 * speed + 0.35        # walker speed <= 1.75 m/s, with slack for seat snapping
        for w in eng.walkers.values():
            if not nav.solid_free(w.x, w.z):
                off_grid += 1
                if off_grid <= 3:
                    problems.append(f"{w.id} off navmesh at ({w.x:.2f},{w.z:.2f}) stage={w.stage}")
            p = last.get(w.id)
            if p and math.dist(p, (w.x, w.z)) > maxstep:
                teleports += 1
                if teleports <= 3:
                    problems.append(f"{w.id} teleported {math.dist(p, (w.x, w.z)):.2f} m stage={w.stage}")
            last[w.id] = (w.x, w.z)
    print(f"[sim] {n_sec:.0f}s x{speed:g}: sim_t={eng.sim_t:.0f}s tickets={len(eng.tickets)} walkers={len(eng.walkers)} "
          f"off-navmesh={off_grid} teleports={teleports} max-pipe={max_pipe}")

    # ---- walk order -------------------------------------------------------------------------
    finished = 0
    for t in eng.tickets.values():
        seq = [s for s, _ in t.trace]
        want = ["enter", "seated"]
        for i in range(1, 6):
            if any(s == f"to_cabin_{i}" for s in seq) or any(s == f"hearing_{i}" for s in seq):
                want += [f"to_cabin_{i}", f"hearing_{i}"]
        got_core = [s for s in seq if s.startswith(("enter", "seated", "to_cabin_", "hearing_"))
                    and s not in ("hearing_exec",)]
        if got_core != want[:len(got_core)] and got_core != want:
            problems.append(f"{t.id} walk order broken: {seq}")
        cabins = [int(s.split("_")[-1]) for s in seq if s.startswith("hearing_") and s != "hearing_exec"]
        if cabins != list(range(1, len(cabins) + 1)):
            problems.append(f"{t.id} cabins out of order: {cabins}")
        if len(t.votes) == 5:
            n = t.approvals
            if n == 5 and "to_exec" in seq:
                problems.append(f"{t.id} 5/5 but visited exec")
            if 3 <= n <= 4 and "hearing_exec" in seq and t.ceo is None and t.finished:
                problems.append(f"{t.id} exec visit without ruling")
            if 3 <= n <= 4 and t.verdict and "to_exec" not in seq:
                problems.append(f"{t.id} split {n}/5 skipped the CEO")
            if n <= 2 and ("to_exec" in seq or t.verdict == "ENTRY"):
                problems.append(f"{t.id} {n}/5 should exit")
            if n == 5 and t.verdict and t.verdict != "ENTRY":
                problems.append(f"{t.id} unanimous not ENTRY")
        if not t.finished and eng.sim_t - t.t0 > 520:
            problems.append(f"{t.id} stuck in stage {t.stage} for {eng.sim_t - t.t0:.0f} sim s")
        if t.finished and 3 <= t.approvals <= 4 and t.ceo is None:
            problems.append(f"{t.id} split council finished without a CEO ruling")
        if t.finished:
            finished += 1
            if seq[-1] != "done":
                problems.append(f"{t.id} finished but trace {seq[-2:]}")
    print(f"[walk] tickets={len(eng.tickets)} finished-walks={finished} unanimous={eng.stats['unanimous']} "
          f"ceo-rulings={eng.stats['ceo_rulings']} entry={eng.stats['entry']} exit={eng.stats['exit']}")

    # ---- funnel -----------------------------------------------------------------------------
    F = eng.hunter.funnel
    prev_out = None
    for s in STAGES:
        st = F["stages"][s]
        if st["out"] > st["in"]:
            problems.append(f"funnel {s}: out>in")
        if prev_out is not None and st["in"] != prev_out:
            problems.append(f"funnel {s}: in({st['in']}) != previous out({prev_out})")
        prev_out = st["out"]
    if prev_out != sum(F["emitted"].values()):
        problems.append("funnel emitted != last stage out")
    ts = sorted(t.t0 for t in eng.tickets.values())
    for a, b in zip(ts, ts[1:]):
        if b - a < GLOBAL_COOLDOWN_S - 1e-6:
            problems.append(f"global cooldown violated: {b - a:.1f}s")
    last_sym: dict[str, float] = {}
    for t in sorted(eng.tickets.values(), key=lambda x: x.t0):
        if t.sym in last_sym and t.t0 - last_sym[t.sym] < SYM_COOLDOWN_S - 1e-6:
            problems.append(f"symbol cooldown violated {t.sym}")
        last_sym[t.sym] = t.t0
        if t.emitter != "fly":
            if abs(t.info.get("rho", 0)) < 0.90:
                problems.append(f"{t.id} correlation trade outside the strong band: {t.info}")
            if t.features.get("corr_age_s", 0) > 60:
                problems.append(f"{t.id} correlation trade on stale table")
        if t.features.get("max_open_rho", 0) >= 0.85:
            problems.append(f"{t.id} violates the correlated-risk gate ({t.features['max_open_rho']})")
        if t.rr < 1.6 - 1e-6 or t.conviction < 0.62 - 1e-6:
            problems.append(f"{t.id} passed funnel below rr/conviction floor")
    if max_pipe > PIPE_CAP:
        problems.append(f"pipe cap exceeded: {max_pipe}")
    print("[funnel] scans={scans} candidates={c} emitted={e}".format(scans=F["scans"], c=F["candidates"], e=F["emitted"]))
    print("         " + "  ".join(f"{s}:{F['stages'][s]['out']}/{F['stages'][s]['in']}" for s in STAGES))

    print(f"[done] {time.time() - t_start:.1f}s wall, {len(problems)} problem(s)")
    for p in problems[:25]:
        print("  !!", p)
    return 1 if problems else 0


if __name__ == "__main__":
    n = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    s = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    sys.exit(main(n, s))
