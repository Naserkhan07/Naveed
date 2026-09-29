"""Information content of the 29 senses: rank IC of each sense vs the forward return (synthetic tape, no engine).

    python backend/tests/deep_study.py [SIM_SECONDS=20000] [HORIZON_S=300] [SEED=7]
Senses 0-11 tape, 12-20 deep stats, 21-24 order book, 25-28 correlation.
"""
import numpy as np

from _common import arg
from soul_exter.brain import senses
from soul_exter.market.corr import CorrelationEngine
from soul_exter.market.tape import Tape


def rank(a):
    return np.argsort(np.argsort(a)).astype(float)


def main():
    sim, hor, seed = arg(1, 20000), int(arg(2, 300)), int(arg(3, 7))
    tape = Tape(seed=seed)
    corr = CorrelationEngine()
    X, P, T = [], [], []
    t = 0.0
    while t < sim:
        tape.advance(30.0); t += 30.0
        try:
            corr.update(tape, t, force=True)
        except Exception:
            pass
        if t % 60 == 0:
            s, _ = senses.compute(tape, corr, None, tape.ts)
            X.append(np.asarray(s)); P.append(np.log(tape.price.copy())); T.append(t)
    steps = max(1, hor // 60)
    ics = []
    for i in range(len(X) - steps):
        fwd = P[i + steps] - P[i]
        ics.append([np.corrcoef(rank(X[i][:, k]), rank(fwd))[0, 1] if X[i][:, k].std() > 1e-9 else 0.0 for k in range(X[i].shape[1])])
    ics = np.nan_to_num(np.array(ics))
    m, sd = ics.mean(axis=0), ics.std(axis=0) / np.sqrt(len(ics))
    grp = lambda k: "tape" if k < 12 else "deep" if k < 21 else "book" if k < 25 else "corr"
    print(f"{len(ics)} snapshots x {X[0].shape[0]} symbols, horizon {hor}s")
    for k in range(len(m)):
        flag = "  *" if abs(m[k]) > 2 * sd[k] else ""
        print(f"sense {k:2d} [{grp(k)}]  IC {m[k]:+.3f}  (se {sd[k]:.3f}){flag}")
    print("\n(the synthetic tape has momentum + mean-reversion regimes, so trend/efficiency senses should show positive IC and stretch senses negative)")


if __name__ == "__main__":
    main()
