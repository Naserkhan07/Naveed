"""Asking the brain a question — the OUTPUT layer.

A query binds (subject, relation) with the current internal state, flows
through the predictive dynamics, and the resulting activation is decoded by
cleanup against the emerging vocabulary. There is no retrieval step: the
answer is whatever the dynamics produce, or "I don't know" when nothing is
activated (the system never reads from a table, because there is none).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from .perception import tokenize

# Question-form priors of the toy perception layer: these are *linguistic*
# patterns, not knowledge. Replaced by learned language dynamics in Phase 5.
_DROP = {"what", "the", "a", "an"}
_R_CAN = re.compile(r"^can (\w+)( do)?$")
_R_PASSIVE = re.compile(r"^is (\w+) by (\w+)$")
_R_DO = re.compile(r"^do(?:es)? (\w+) (\w+)$")
_R_INVERSE = re.compile(r"^(\w+) (\w+)$")


@dataclass
class Answer:
    concept: str | None
    confidence: float
    activation_norm: float


def ask(brain, subject: str | None, relation: str | None, use_state: bool = False) -> Answer:
    """Query the dynamics. Unknown words -> no answer (never hallucinate)."""
    if subject is None or relation is None:
        return Answer(None, 0.0, 0.0)
    if not brain.vocab.has(subject) or not brain.vocab.has(relation):
        return Answer(None, 0.0, 0.0)
    perc = brain.perceiver()
    h = brain.state.h if use_state else np.zeros(brain.config.dim)
    x = perc.encode_query(subject, relation, state_h=h)
    y = brain.net.forward(x)
    concept, conf = brain.vocab.nearest(y)
    return Answer(concept=concept, confidence=conf, activation_norm=float(np.linalg.norm(y)))


def parse_question(surface: str) -> tuple[str, str] | None:
    """Parse a natural toy-language question into a (subject, relation) query.

    'what does the fire burn?'   ->  (fire, burns)
    'what is heated by the sun?' ->  (sun, heats)
    'what heats the water?'      ->  (water, inv_heats)
    'what can the bird do?'      ->  (bird, can)
    'fire / burns / ?'           ->  (fire, burns)
    """
    text = surface.strip().lower().rstrip("?").strip()
    if "/" in text:
        parts = [p.strip() for p in text.split("/")]
        if len(parts) == 3 and parts[2] == "?":
            return parts[0], parts[1]
        return None

    flat = " ".join(t for t in tokenize(text) if t not in _DROP)

    m = _R_CAN.match(flat)
    if m:
        return m.group(1), "can"
    m = _R_PASSIVE.match(flat)
    if m:
        return m.group(2), m.group(1)
    m = _R_DO.match(flat)
    if m:
        return m.group(1), m.group(2)
    m = _R_INVERSE.match(flat)
    if m:
        return m.group(2), "inv_" + m.group(1)
    return None


def answer_surface(brain, surface: str) -> Answer | None:
    """Parse a question, then ask the dynamics."""
    parsed = parse_question(surface)
    if parsed is None:
        return None
    return ask(brain, *parsed)
