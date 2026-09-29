"""Offline answerer regression: every question type must get a substantive, non-refusal answer where the KB covers it."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from soul_exter.llm import offline  # noqa: E402

CASES = {
    "what is rsi": "momentum", "capital of india": "New Delhi", "what is 15% of 240": "36",
    "explain position sizing": "risk", "who wrote hamlet": "Shakespeare", "what is a stop loss": "loss",
    "capital of france and what is 2+2": "Paris", "convert 5 km to miles": "mi", "tell me a joke": "",
}
bad = 0
for q, must in CASES.items():
    a = offline.answer(q)
    ok = must.lower() in a.lower() and "looks like" not in a
    bad += not ok
    print(("ok  " if ok else "FAIL"), q, "->", a[:70].replace("\n", " "))
u = offline.answer("what is the population of the fictional planet zorgon")
assert "built-in knowledge" in u, u          # unknown -> honest, never an invented fact
print("problems:", bad)
sys.exit(1 if bad else 0)
