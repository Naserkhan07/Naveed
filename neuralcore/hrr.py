"""REPRESENTATION layer: Holographic Reduced Representations (HRR).

Concepts live as vectors in a shared high-dimensional space. Composite
experience (subject x relation, or "role x filler") is bound into a single
vector with circular convolution. Bound information is holographic: every
dimension participates in every concept, and any piece can be recovered by
unbinding with the (approximately) inverse key.

This is the substrate that makes distributed knowledge (manifesto section 7)
structural rather than aspirational: there is no table anywhere, only
superposed dynamics.
"""

from __future__ import annotations

import numpy as np

_EPS = 1e-9


class HRRSpace:
    """Vector space + binding algebra. dim ~ 256 gives a good capacity/size trade."""

    def __init__(self, dim: int, seed: int = 0):
        self.dim = int(dim)
        self.rng = np.random.default_rng(seed)

    def random_vector(self) -> np.ndarray:
        """A fresh (emerging) concept vector.

        Unitary HRR: a real vector whose Fourier spectrum has constant
        magnitude (Hermitian-symmetric random phases). Binding is then
        norm-preserving and the exact inverse key is just the conjugate
        spectrum — no division, no noise amplification — so superposed
        memories stay decodable as experience accumulates.
        """
        d = self.dim
        spec = np.zeros(d, dtype=complex)
        spec[0] = np.sqrt(d) * self.rng.choice([-1.0, 1.0])
        if d % 2 == 0:
            spec[d // 2] = np.sqrt(d) * self.rng.choice([-1.0, 1.0])
        half = d // 2
        phases = self.rng.uniform(0.0, 2.0 * np.pi, half - (1 if d % 2 == 0 else 0))
        for i, ph in enumerate(phases, start=1):
            spec[i] = np.sqrt(d) * np.exp(1j * ph)
            spec[d - i] = np.conj(spec[i])
        v = np.real(np.fft.ifft(spec))
        return v / (np.linalg.norm(v) + _EPS)

    # -- algebra -----------------------------------------------------------

    @staticmethod
    def bind(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Circular convolution: one vector that carries both, holographically."""
        return np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))

    @staticmethod
    def unbound_key(b: np.ndarray) -> np.ndarray:
        """Exact algebraic inverse of b under binding (up to numerics)."""
        B = np.fft.fft(b)
        inv = np.conj(B) / (np.abs(B) ** 2 + _EPS)
        v = np.real(np.fft.ifft(inv))
        return v / (np.linalg.norm(v) + _EPS)

    @staticmethod
    def unbind(composite: np.ndarray, key: np.ndarray) -> np.ndarray:
        """Recover the other member: unbind(bind(a,b), key(b)) ~ a."""
        return HRRSpace.bind(composite, HRRSpace.unbound_key(key))

    @staticmethod
    def superpose(vectors: list[np.ndarray]) -> np.ndarray:
        """Experience accumulates by addition — superposed traces share space."""
        m = np.sum(vectors, axis=0)
        return m / (np.linalg.norm(m) + _EPS)

    @staticmethod
    def cosine(u: np.ndarray, v: np.ndarray) -> float:
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        if nu < _EPS or nv < _EPS:
            return 0.0
        return float(np.dot(u, v) / (nu * nv))
