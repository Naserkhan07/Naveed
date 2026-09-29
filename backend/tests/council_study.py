"""Does the 5-judge council add value?  Outcome (paper R) by number of approvals, by judge and by verdict path.

    python backend/tests/council_study.py [SIM_SECONDS=6000] [SEED=7]
"""
from _common import arg, mean, resolved, run_engine, table
from soul_exter.llm.seats import JUDGES


def main():
    sim, seed = arg(1, 6000), int(arg(2, 7))
    eng = run_engine(sim, seed)
    res = [t for t in resolved(eng) if len(t.votes) == 5]
    print(f"sim {eng.sim_t:.0f}s  tickets with a full council and a paper result: {len(res)}")
    rows = []
    for n in range(6):
        ts = [t for t in res if t.approvals == n]
        rows.append([f"{n}/5 approve", len(ts), f"{mean(t.r for t in ts):+.2f}" if ts else "-", f"{sum(1 for t in ts if t.r > 0) / len(ts):.0%}" if ts else "-"])
    print(table(rows, ["approvals", "n", "avgR", "win"]))
    print(f"\nsplit of verdicts: 5/5 {sum(t.approvals == 5 for t in res) / max(1, len(res)):.0%} · 3-4 {sum(3 <= t.approvals <= 4 for t in res) / max(1, len(res)):.0%} · <=2 {sum(t.approvals <= 2 for t in res) / max(1, len(res)):.0%}")
    rows = []
    for s in JUDGES:
        ap = [t for t in res if any(v.seat == s and v.approve for v in t.votes)]
        rj = [t for t in res if any(v.seat == s and not v.approve for v in t.votes)]
        rows.append([s, f"{len(ap) / max(1, len(res)):.0%}", f"{mean(t.r for t in ap):+.2f}" if ap else "-", f"{mean(t.r for t in rj):+.2f}" if rj else "-",
                     f"{(mean(t.r for t in ap) - mean(t.r for t in rj)):+.2f}" if ap and rj else "-"])
    print("\nper judge (edge = avgR when approved − avgR when rejected; >0 means the seat adds information):")
    print(table(rows, ["judge", "approve", "avgR|appr", "avgR|rej", "edge"]))
    print("\ncouncil stats:", eng.council_stats())


if __name__ == "__main__":
    main()
