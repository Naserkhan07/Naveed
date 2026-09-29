"""The seven seats.  Every desk runs the keyless free cloud GPT by default; the persona names
below are only the *judging temperament* used inside cabin verdict prompts and offline reasoning —
they never leak into ordinary Q&A (the system contract forbids pivoting to persona)."""
from __future__ import annotations

from ..core.layout import PALETTE

SEATS: dict[str, dict] = {
    "ATLAS": {"cabin": 1, "persona": "Llama-3.3-70B", "hosted": "meta-llama/llama-3.3-70b-instruct", "groq": "llama-3.3-70b-versatile",
              "lens": "trend structure and momentum", "weights": {"trend": 1.0, "mom": 0.8, "brk": 0.5}},
    "QUANTA": {"cabin": 2, "persona": "Qwen2.5-72B", "hosted": "qwen/qwen-2.5-72b-instruct", "groq": None,
               "lens": "statistical edge: variance ratio, autocorrelation, skew", "weights": {"vr": 1.0, "ac": 0.6, "eff": 0.7}},
    "MERIDIAN": {"cabin": 3, "persona": "DeepSeek-V3", "hosted": "deepseek/deepseek-chat", "groq": None,
                 "lens": "cross-asset context: correlation blocs and currency strength", "weights": {"corr": 1.0, "ccy": 0.8, "lead": 0.5}},
    "VOLTA": {"cabin": 4, "persona": "Mixtral-8x7B", "hosted": "mistralai/mixtral-8x7b-instruct", "groq": None,
              "lens": "volatility and liquidity", "weights": {"vol": 1.0, "flow": 0.7, "liq": 0.6}},
    "VECTOR": {"cabin": 5, "persona": "Phi-4", "hosted": "microsoft/phi-4", "groq": None,
               "lens": "risk: reward-to-risk, costs and crowding", "weights": {"rr": 1.0, "cost": 0.9, "risk": 0.7}},
    "NAVEED": {"cabin": 0, "persona": "Hermes-3-405B (CEO)", "hosted": "nousresearch/hermes-3-llama-3.1-405b", "groq": None,
               "lens": "final ruling on split panels", "weights": {}},
    "DROSOPHILA": {"cabin": 0, "persona": "fly scout", "hosted": "meta-llama/llama-3.3-70b-instruct", "groq": None,
                   "lens": "the mushroom-body scout that hunts trades", "weights": {}},
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
