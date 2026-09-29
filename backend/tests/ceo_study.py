"""How does CEO NAVEED rule on split (3-4 of 5) councils, and are the rulings worth it?

    python backend/tests/ceo_study.py [SIM_SECONDS=8000] [SEED=7]
"""
from _common import arg, mean, run_engine, table


def main():
    sim, seed = arg(1, 8000), int(arg(2, 7))
    eng = run_engine(sim, seed)
    split = [t for t in eng.tickets.values() if 3 <= t.approvals <= 4 and t.ceo]
    print(f"sim {eng.sim_t:.0f}s  split councils ruled by the CEO: {len(split)}")
    if not split:
        print("no rulings yet — raise SIM_SECONDS"); return
    rows = []
    for name, ts in (("approved", [t for t in split if t.ceo["vote"] == "approve"]), ("rejected", [t for t in split if t.ceo["vote"] != "approve"])):
        rs = [t.r for t in ts if t.r is not None]
        rows.append([name, len(ts), len(rs), f"{mean(rs):+.2f}" if rs else "-", f"{sum(r > 0 for r in rs) / len(rs):.0%}" if rs else "-"])
    print(table(rows, ["CEO ruling", "n", "resolved", "avgR", "win"]))
    for a in (3, 4):
        ts = [t for t in split if t.approvals == a]
        ap = sum(t.ceo["vote"] == "approve" for t in ts)
        print(f"  {a}/5 councils: {len(ts)} ruled, CEO approved {ap} ({ap / max(1, len(ts)):.0%})")
    print("\ndoctrine notes:", len(eng.doctrine))


if __name__ == "__main__":
    main()
