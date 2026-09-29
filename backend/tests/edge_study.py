"""Edge of the fly's emissions: paper R by conviction bucket, R:R bucket and brain state at emission — is conviction calibrated?

    python backend/tests/edge_study.py [SIM_SECONDS=8000] [SEED=7]
"""
from _common import arg, mean, resolved, run_engine, table


def bucket(ts, key, edges, label):
    rows = []
    for lo, hi in zip(edges, edges[1:]):
        b = [t for t in ts if lo <= key(t) < hi]
        rows.append([f"{lo:.2f}-{hi:.2f}", len(b), f"{mean(t.r for t in b):+.2f}" if b else "-", f"{sum(t.r > 0 for t in b) / len(b):.0%}" if b else "-"])
    print(f"\n{label}\n" + table(rows, ["range", "n", "avgR", "win"]))


def main():
    sim, seed = arg(1, 8000), int(arg(2, 7))
    eng = run_engine(sim, seed)
    res = resolved(eng)
    print(f"sim {eng.sim_t:.0f}s  resolved {len(res)}  overall avgR {mean(t.r for t in res):+.3f}")
    if len(res) < 5:
        print("too few outcomes — raise SIM_SECONDS"); return
    bucket(res, lambda t: t.conviction, [0.62, 0.68, 0.74, 0.80, 0.90, 1.01], "conviction")
    bucket(res, lambda t: t.rr, [1.6, 1.8, 2.0, 2.4, 9.0], "reward : risk")
    bucket(res, lambda t: t.features.get("trend", 0) if isinstance(t.features, dict) else 0, [-2, 0, 0.5, 2], "trend feature at emission (if recorded)")
    F = eng.hunter.funnel
    print("\nfunnel:", {s: f"{v['out']}/{v['in']}" for s, v in F["stages"].items()}, "emitted", F["emitted"])


if __name__ == "__main__":
    main()
