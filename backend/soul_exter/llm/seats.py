"""The seven seats.  Every desk runs the keyless free cloud GPT by default; the persona names
below are only the *judging temperament* used inside cabin verdict prompts and offline reasoning —
they never leak into ordinary Q&A (the system contract forbids pivoting to persona)."""
from __future__ import annotations

from ..core.layout import PALETTE

# `persona` = the open-source model this desk is meant to run (Kaggle/Ollama defaults, see kaggle/).  The token after the
# name is only the *judging temperament*; it never leaks into ordinary Q&A (the system contract forbids pivoting to persona).
SEATS: dict[str, dict] = {
    "ATLAS": {"cabin": 1, "persona": "Llama-3.1-8B", "ollama": "llama3.1:8b",
              "role": "Chief Technical Strategist", "lens": "trend structure and momentum",
              "bio": "20 years reading market structure: trend, swing highs/lows, breakouts, momentum and multi-timeframe alignment.",
              "weights": {"trend": 1.0, "mom": 0.8, "brk": 0.5}},
    "QUANTA": {"cabin": 2, "persona": "Qwen2.5-7B", "ollama": "qwen2.5:7b",
               "role": "Head of Quantitative Research", "lens": "statistical edge: variance ratio, autocorrelation, skew",
               "bio": "Quant researcher: expectancy in R, variance ratio, autocorrelation, efficiency ratio, sample size and overfitting risk.",
               "weights": {"vr": 1.0, "ac": 0.6, "eff": 0.7}},
    "MERIDIAN": {"cabin": 3, "persona": "Mistral-7B", "ollama": "mistral:7b",
                 "role": "Global Macro & Cross-Asset Strategist", "lens": "cross-asset context: correlation blocs and currency strength",
                 "bio": "Macro strategist: currency strength, rate differentials, risk-on/off, correlation blocs and session liquidity.",
                 "weights": {"corr": 1.0, "ccy": 0.8, "lead": 0.5}},
    "VOLTA": {"cabin": 4, "persona": "Gemma-2-9B", "ollama": "gemma2:9b",
              "role": "Volatility & Liquidity Desk Head", "lens": "volatility and liquidity",
              "bio": "Volatility trader: ATR regimes, vol bursts, spreads, order-flow imbalance, slippage and session liquidity.",
              "weights": {"vol": 1.0, "flow": 0.7, "liq": 0.6}},
    "VECTOR": {"cabin": 5, "persona": "Phi-3-Mini", "ollama": "phi3:mini",
               "role": "Chief Risk Officer", "lens": "risk: reward-to-risk, costs and crowding",
               "bio": "Risk officer: reward-to-risk, position sizing, costs, correlated exposure and drawdown control.",
               "weights": {"rr": 1.0, "cost": 0.9, "risk": 0.7}},
    "NAVEED": {"cabin": 0, "persona": "Qwen2.5-7B (CEO)", "ollama": "qwen2.5:7b",
               "role": "CEO · Head of the Floor", "lens": "final ruling on split panels",
               "bio": "The CEO: weighs the council's dossier, the floor's recent results and total risk, then rules on split panels.",
               "weights": {}},
    "DROSOPHILA": {"cabin": 0, "persona": "Fly brain + Qwen2.5-7B", "ollama": "qwen2.5:7b",
                   "role": "Market Hunter (fly brain)", "lens": "the mushroom-body scout that hunts trades",
                   "bio": "The fly-brain scout: 29 glomeruli, 140 Kenyon cells, 8 output neurons; learns from dopamine on every realised R.",
                   "weights": {}},
}
JUDGES = ["ATLAS", "QUANTA", "MERIDIAN", "VOLTA", "VECTOR"]
COLORS: dict[str, str] = PALETTE["seat_colors"]


def seat_by_cabin(i: int) -> str:
    return JUDGES[i - 1]


def resolve_seat(seat_id: str | int | None) -> str:
    """accept 'atlas', 'ATLAS', 'desk_3', 3 ..."""
    if seat_id is None:
        return "ATLAS"
    s = str(seat_id).strip().upper()
    if s in SEATS:
        return s
    digits = "".join(c for c in s if c.isdigit())
    if digits:
        return list(SEATS)[int(digits) % len(SEATS)]
    return "ATLAS"
