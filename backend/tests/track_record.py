"""Paper track record of everything the fly sent to the floor (entered AND rejected, so the council's value is visible).

    python backend/tests/track_record.py [SIM_SECONDS=6000] [SEED=7]
"""
from _common import arg, mean, resolved, run_engine, table


def main():
    sim, seed = arg(1, 6000), int(arg(2, 7))
    eng = run_engine(sim, seed)
    res = resolved(eng)
    print(f"sim {eng.sim_t:.0f}s  tickets {len(eng.tickets)}  resolved {len(res)}  brain updates {eng.hunter.brain.n_updates}  dopamine {eng.hunter.brain.dopamine:+.2f}")
    if not res:
        print("nothing resolved yet — raise SIM_SECONDS"); return
    def row(name, ts):
        rs = [t.r for t in ts]
        wins = sum(1 for r in rs if r > 0)
        return [name, len(ts), f"{wins / len(ts):.0%}" if ts else "-", f"{mean(rs):+.2f}", f"{sum(rs):+.1f}"]
    rows = [row("all", res)]
    for v in ("ENTRY", "EXIT"):
        rows.append(row(f"verdict {v}", [t for t in res if t.verdict == v]))
    for p in sorted({t.verdict_path for t in res if t.verdict_path}):
        rows.append(row(f"path {p}", [t for t in res if t.verdict_path == p]))
    for c in sorted({t.cls for t in res}):
        rows.append(row(f"class {c}", [t for t in res if t.cls == c]))
    for e in sorted({t.emitter for t in res}):
        rows.append(row(f"emitter {e}", [t for t in res if t.emitter == e]))
    for d in ("LONG", "SHORT"):
        rows.append(row(d, [t for t in res if (t.direction > 0) == (d == "LONG")]))
    print(table(rows, ["bucket", "n", "win", "avgR", "sumR"]))
    print("\nplaybook (top buckets):")
    pb = sorted(eng.playbook.items(), key=lambda kv: -kv[1]["n"])[:10]
    print(table([[k, v["n"], f"{v['sumR'] / v['n']:+.2f}"] for k, v in pb], ["emitter|class|side|regime", "n", "avgR"]))


if __name__ == "__main__":
    main()
