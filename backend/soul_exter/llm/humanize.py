"""Human conversational layer: warm, whole-word glossary matching, follow-up question only ~18 %
of the time and never after a '?'."""
from __future__ import annotations

import hashlib
import random
import re

FOLLOW_RATE = 0.18
OPENERS = ["Sure — ", "Happy to help. ", "Good question. ", "Glad you asked. "]
FOLLOWUPS = ["Want me to go a little deeper on any part of that?", "Does that cover what you were after?",
             "Should I give an example?", "Is there a particular angle you care about?"]

GLOSSARY: dict[str, str] = {
    "photosynthesis": "the process plants, algae and some bacteria use to turn light, water and carbon dioxide into sugar and oxygen.",
    "gravity": "the attraction between masses; on Earth it accelerates falling objects at about 9.8 m/s².",
    "inflation": "a general rise in prices over time, which reduces what each unit of money can buy.",
    "recursion": "when a function solves a problem by calling itself on a smaller piece of it, until it reaches a base case.",
    "api": "an application programming interface — a defined way for one program to ask another to do something.",
    "http": "the HyperText Transfer Protocol, the request/response language web browsers and servers use.",
    "dns": "the Domain Name System, which translates names like example.com into IP addresses.",
    "python": "a popular, readable general-purpose programming language.",
    "blockchain": "an append-only ledger where blocks of records are chained together with hashes and agreed by a network.",
    "neuron": "a nerve cell that receives signals through dendrites and sends them along an axon.",
    "dopamine": "a neuromodulator involved in reward prediction, motivation and learning.",
    "algorithm": "a finite, step-by-step procedure for solving a problem.",
    "entropy": "a measure of disorder, or of how much information is needed to describe a system's state.",
    "democracy": "a system of government in which power rests with the people, usually through voting.",
    "atr": "average true range, a measure of how far a price typically moves per bar.",
    "spread": "the gap between the best bid and best ask price.",
    "volatility": "how much and how fast a value moves around.",
    "drawdown": "the fall from a peak to a subsequent low in an account or price series.",
    "stop loss": "an order that closes a position at a preset loss level.",
    "correlation": "how closely two things move together, from -1 (opposite) to +1 (in lockstep).",
    "pearson": "Pearson's r, the standard linear correlation coefficient between two series.",
    "momentum": "the tendency of something that has been moving in one direction to keep going.",
    "liquidity": "how easily something can be bought or sold without moving its price much.",
    "derivative": "in maths, the rate of change of a function; in finance, a contract whose value depends on another asset.",
    "integral": "the accumulated area under a curve; the reverse of differentiation.",
    "machine learning": "methods where programs learn patterns from data instead of being explicitly programmed.",
    "llm": "a large language model — a neural network trained on text to predict and generate language.",
    "git": "a distributed version control system for tracking changes to files.",
    "tcp": "the Transmission Control Protocol, which delivers ordered, reliable byte streams over IP.",
    "sql": "Structured Query Language, used to query and manage relational databases.",
    "pi": "the ratio of a circle's circumference to its diameter, about 3.14159.",
    "prime number": "a whole number greater than 1 whose only divisors are 1 and itself.",
    "fibonacci": "a sequence where each number is the sum of the previous two: 0, 1, 1, 2, 3, 5, 8…",
}
_GLOSS_RE = {k: re.compile(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])", re.I) for k in GLOSSARY}


def glossary_hits(text: str) -> list[str]:
    """whole-word matching only ('atr' must not hit 'atrium', 'pi' must not hit 'pipe')"""
    return [k for k, rx in _GLOSS_RE.items() if rx.search(text)]


def _rng(question: str, salt: str = "") -> random.Random:
    h = hashlib.sha256((question + salt).encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def trim_words(text: str, limit: int = 170) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    cut = " ".join(words[:limit])
    m = list(re.finditer(r"[.!?](?=\s|$)", cut))
    if m and m[-1].end() > len(cut) * 0.55:
        return cut[: m[-1].end()]
    return cut.rstrip(",;:") + "…"


def humanize(text: str, question: str, salt: str = "") -> str:
    text = re.sub(r"\s+\n", "\n", text.strip())
    text = trim_words(text)
    rng = _rng(question, salt)
    ends_q = text.rstrip().endswith("?")
    greeting = bool(re.match(r"^\s*(hi|hello|hey|thanks|thank you|good (morning|evening|afternoon))\b", question, re.I))
    if not greeting and question.strip().endswith("?") and rng.random() < 0.25 and not text.lower().startswith(("sure", "happy", "good question", "glad")):
        text = rng.choice(OPENERS) + text[0].lower() + text[1:] if text[:2].isalpha() and not text[:2].isupper() else text
    # follow-up: ~18 %, never after a '?', never when the answer already asks something
    if not ends_q and "?" not in text[-80:] and rng.random() < FOLLOW_RATE:
        text = text.rstrip() + " " + rng.choice(FOLLOWUPS)
    return text
