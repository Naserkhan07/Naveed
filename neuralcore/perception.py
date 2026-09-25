"""PERCEPTION layer: raw experience -> neural activations.

Text / event tuples are parsed and composed into vectors through an
*emerging vocabulary*: the first time the system experiences a word it
receives a random sensory vector; from then on that word IS that vector.
The vocabulary is part of the neural system (like a sensory cortex), not a
knowledge table — it maps symbols to activations, it stores no facts.

Because vocab vectors live inside the brain file, inference needs zero
external data (manifesto sections 9 and 10). We are explicit that some
physical state must persist — ours is the minimal sensorium + weights.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from .hrr import HRRSpace

_EPS = 1e-9

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Linguistic prior: surface forms of the same verb/word map to one concept.
# This is grammar, not knowledge — replaced by learned language dynamics in
# Phase 5 of the roadmap.
_LEMMA = {
    "makes": "make", "made": "make", "making": "make",
    "heats": "heat", "heated": "heat", "heating": "heat",
    "burns": "burn", "burned": "burn", "burning": "burn",
    "cools": "cool", "cooled": "cool", "cooling": "cool",
    "freezes": "freeze", "frozen": "freeze", "freezing": "freeze",
    "moves": "move", "moved": "move", "moving": "move",
    "wets": "wet", "wetted": "wet",
    "grows": "grow", "grown": "grow", "growing": "grow",
    "forges": "forge", "forged": "forge", "forging": "forge",
    "treats": "treat", "treated": "treat", "treating": "treat",
    "writes": "write", "written": "write", "writing": "write",
    "builds": "build", "built": "build", "building": "build",
    "becomes": "become", "became": "become", "becoming": "become",
    "follows": "follow", "followed": "follow", "following": "follow",
    "has": "has", "had": "has", "having": "has",
    "lives": "live", "lived": "live", "living": "live",
    "is": "is", "was": "is", "were": "is", "are": "is",
    "can": "can", "could": "can",
    # agent nouns: never strip -er (would collide with the verb, e.g. builder/build)
    "farmer": "farmer", "builder": "builder", "baker": "baker",
    "writer": "writer", "reader": "reader", "teacher": "teacher",
    "driver": "driver", "worker": "worker", "player": "player",
    "singer": "singer", "dancer": "dancer", "swimmer": "swimmer",
    "runner": "runner", "owner": "owner", "maker": "maker",
}

_SUFFIXES = ("ing", "ers", "er", "ed", "es", "s")


def normalize_word(w: str) -> str:
    """Surface form -> concept key. Lemma map first, then a conservative
    plural/inflection strip that never mangles short words ('water' stays
    'water'; 'wings' -> 'wing')."""
    w = w.strip().lower()
    if w.startswith("inv_"):
        # inverse-relation markers normalize by their head word, so the
        # training path (f"inv_{surface_verb}") and the question parser
        # (f"inv_{lemma}") always derive the same concept key.
        return "inv_" + normalize_word(w[4:])
    if w in _LEMMA:
        return _LEMMA[w]
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: len(w) - len(suf)]
    return w


def tokenize(sentence: str) -> list[str]:
    return [normalize_word(t) for t in _TOKEN_RE.findall(sentence.lower())]


@dataclass
class Experience:
    """One moment of experience: a sentence and its structured event reading."""

    sentence: str
    subject: str | None = None
    relation: str | None = None
    object: str | None = None

    def tokens(self) -> list[str]:
        return tokenize(self.sentence)


class EmergingVocabulary:
    """Symbol -> activation map. Part of the brain, grows with experience."""

    def __init__(self, space: HRRSpace):
        self.space = space
        self.words: dict[str, int] = {}
        self.vectors: list[np.ndarray] = []
        self.order: list[str] = []          # index -> word, parallel to vectors
        self._matrix_cache: np.ndarray | None = None

    def get(self, word: str) -> np.ndarray:
        w = normalize_word(word)
        idx = self.words.get(w)
        if idx is None:
            idx = len(self.vectors)
            self.words[w] = idx
            self.vectors.append(self.space.random_vector())
            self.order.append(w)
            self._matrix_cache = None       # invalidate: the sensorium grew
        return self.vectors[idx]

    def has(self, word: str) -> bool:
        return normalize_word(word) in self.words

    def _matrix(self) -> np.ndarray:
        if self._matrix_cache is None:
            self._matrix_cache = np.array(self.vectors)
        return self._matrix_cache

    def nearest(self, v: np.ndarray) -> tuple[str | None, float]:
        """Cleanup: decode an activation to the closest known concept.
        Vectorized over the whole vocabulary (one matmul) — this is what
        makes large-scale inference fast."""
        if not self.vectors:
            return None, 0.0
        M = self._matrix()
        nv = np.linalg.norm(v)
        if nv < _EPS:
            return None, 0.0
        sims = (M @ v) / (np.linalg.norm(M, axis=1) * nv + _EPS)
        i = int(np.argmax(sims))
        return self.order[i], float(sims[i])

    def __len__(self) -> int:
        return len(self.vectors)

    # -- serialization (part of the brain file) ---------------------------

    def state_dict(self) -> dict:
        return {"words": list(self.order), "vectors": np.array(self.vectors)}

    @classmethod
    def from_state_dict(cls, space: HRRSpace, sd: dict) -> "EmergingVocabulary":
        vocab = cls(space)
        for w, v in zip(sd["words"], sd["vectors"]):
            vocab.words[w] = len(vocab.vectors)
            vocab.vectors.append(np.asarray(v, dtype=float))
            vocab.order.append(w)
        return vocab


class Perceiver:
    """Composes experiences into input activations for the neural dynamics."""

    def __init__(self, space: HRRSpace, vocab: EmergingVocabulary, context_weight: float = 0.35):
        self.space = space
        self.vocab = vocab
        self.context_weight = context_weight

    def encode_event(self, subject: str, relation: str, obj: str) -> np.ndarray:
        """(subject, relation) binding — the address of an experience."""
        return self.space.bind(self.vocab.get(subject), self.vocab.get(relation))

    def encode_query(self, subject: str, relation: str, state_h: np.ndarray | None = None) -> np.ndarray:
        """A question becomes an activation: binding + current internal state."""
        x = self.encode_event(subject, relation, "?")
        if state_h is not None and self.context_weight > 0:
            x = x + self.context_weight * state_h
        n = np.linalg.norm(x)
        return x / n if n > 0 else x

    def parse_sentence(self, exp: Experience) -> Experience:
        """Fill in missing event slots from the sentence surface form."""
        s, r, o = exp.subject, exp.relation, exp.object
        if s and r and o:
            return exp
        toks = exp.tokens()
        if not toks:
            return exp
        if s is None:
            s = toks[0]
        if r is None and len(toks) > 1:
            r = toks[1]
        if o is None and len(toks) > 2:
            o = toks[-1]
        return Experience(sentence=exp.sentence, subject=s, relation=r, object=o)
