"""The brain: one file containing the entire neural system.

Brain file (.ncb — neural core brain) contents, i.e. ALL that exists after
training:
  - predictive network weights           (learned dynamics / "knowledge")
  - emerging vocabulary vectors          (sensory cortex — symbol->activation
                                          mappings only; zero facts inside)
  - recurrent neural state               (residual context trace)
  - synaptic importance traces           (metaplastic state)
  - architecture hyperparameters

No experiences, no sentences, no fact lists. Delete the training data, keep
the brain, and the system still answers — that is the experiment. The file
is plain compressed arrays (no pickle), so you can inspect every byte.
"""

from __future__ import annotations

import io
import json
from dataclasses import asdict, dataclass, field

import numpy as np

from .hrr import HRRSpace
from .network import PredictiveNetwork
from .perception import EmergingVocabulary, Perceiver
from .scheduler import MetaplasticScheduler, SchedulerConfig
from .state import NeuralState


@dataclass
class BrainConfig:
    dim: int = 256
    hidden: int = 512
    sparsity_k: int = 48
    state_alpha: float = 0.6
    context_weight: float = 0.35
    seed: int = 0
    gate_lambda: float = 0.0


@dataclass
class Brain:
    config: BrainConfig
    space: HRRSpace
    net: PredictiveNetwork
    vocab: EmergingVocabulary
    state: NeuralState
    scheduler: MetaplasticScheduler
    meta: dict = field(default_factory=dict)

    @classmethod
    def build(cls, config: BrainConfig | None = None) -> "Brain":
        cfg = config or BrainConfig()
        space = HRRSpace(cfg.dim, seed=cfg.seed)
        net = PredictiveNetwork(cfg.dim, cfg.hidden, seed=cfg.seed, sparsity_k=cfg.sparsity_k)
        vocab = EmergingVocabulary(space)
        state = NeuralState(cfg.dim, alpha=cfg.state_alpha)
        scheduler = MetaplasticScheduler(
            net, SchedulerConfig(gate_lambda=cfg.gate_lambda)
        )
        return cls(config=cfg, space=space, net=net, vocab=vocab, state=state, scheduler=scheduler)

    def perceiver(self) -> Perceiver:
        return Perceiver(self.space, self.vocab, context_weight=self.config.context_weight)

    # -- serialization (flat arrays only — no pickle, no opaque objects) ------

    def _payload(self) -> dict[str, np.ndarray]:
        # stored as float32: half the bytes, ample precision for inference
        payload: dict[str, np.ndarray] = {}
        for name, p in self.net.named_parameters().items():
            payload[f"net_{name}"] = p.astype(np.float32)
        for name, o in self.scheduler.omega.items():
            payload[f"omega_{name}"] = o.astype(np.float32)
        payload["vocab_words"] = np.array(
            [w for w, _ in sorted(self.vocab.words.items(), key=lambda kv: kv[1])], dtype="<U32"
        )
        payload["vocab_vectors"] = np.array(self.vocab.vectors, dtype=np.float32)
        payload["state_h"] = self.state.h.astype(np.float32)
        payload["state_alpha"] = np.array([self.state.alpha])
        payload["config"] = np.frombuffer(
            json.dumps(asdict(self.config)).encode("utf-8"), dtype=np.uint8
        )
        payload["meta"] = np.frombuffer(json.dumps(self.meta).encode("utf-8"), dtype=np.uint8)
        return payload

    def _to_bytes(self) -> bytes:
        buf = io.BytesIO()
        np.savez_compressed(buf, **self._payload())
        return buf.getvalue()

    def save(self, path: str) -> int:
        """Serialize to a single .ncb file. Returns byte size."""
        data = self._to_bytes()
        with open(path, "wb") as f:
            f.write(data)
        return len(data)

    def byte_size(self) -> int:
        return len(self._to_bytes())

    @classmethod
    def load(cls, path: str) -> "Brain":
        with open(path, "rb") as f:
            data = f.read()
        z = np.load(io.BytesIO(data), allow_pickle=False)
        cfg = BrainConfig(**json.loads(bytes(z["config"]).decode("utf-8")))
        meta = json.loads(bytes(z["meta"]).decode("utf-8")) if "meta" in z else {}

        brain = cls.build(cfg)
        brain.net.load_state_dict(
            {k: z[f"net_{k}"].astype(np.float64) for k in ("W1", "b1", "W2", "b2")}
        )
        words = [str(w) for w in z["vocab_words"]]
        vectors = np.asarray(z["vocab_vectors"], dtype=float)
        brain.vocab.words = {w: i for i, w in enumerate(words)}
        brain.vocab.vectors = [vectors[i] for i in range(len(words))]
        brain.state.load_state_dict({"h": z["state_h"], "alpha": z["state_alpha"]})
        brain.scheduler.load_state_dict({f"omega_{k}": z[f"omega_{k}"] for k in ("W1", "b1", "W2", "b2")})
        brain.meta = meta
        return brain
