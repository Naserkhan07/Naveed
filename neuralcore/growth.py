"""STRUCTURAL GROWTH — the bot gets bigger when experience exceeds capacity.

This is the flowchart's `increase scale` branch made physical. When a block
of experience cannot be learned to target (the system keeps being surprised),
the brain GROWS: new silent neurons are added (existing knowledge untouched),
and the next passes wire them up. Brain file bytes rise accordingly.

The policy is deliberately conservative: grow only on demonstrated capacity
pressure, cooldown between growths, hard ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class GrowthPolicy:
    confidence_floor: float = 0.50   # final-epoch confidence below this = pressure
    delta_frac: float = 0.25         # grow by 25% of current hidden layer
    max_hidden: int = 3072           # hard ceiling
    cooldown: int = 1                # blocks to wait between growths


class GrowthTracker:
    def __init__(self, policy: GrowthPolicy):
        self.policy = policy
        self._cooldown_left = 0
        self.events: list[dict] = []

    def should_grow(self, final_confidence: float) -> tuple[bool, str]:
        if self._cooldown_left > 0:
            self._cooldown_left -= 1
            return False, "cooldown"
        if final_confidence >= self.policy.confidence_floor:
            return False, f"confident ({final_confidence:.2f} >= {self.policy.confidence_floor:.2f})"
        return True, f"capacity pressure ({final_confidence:.2f} < {self.policy.confidence_floor:.2f})"

    def apply(self, brain, final_confidence: float) -> int:
        """Check the policy and grow if needed. Returns neurons added (0 if none)."""
        grow, reason = self.should_grow(final_confidence)
        if not grow:
            return 0
        current = brain.net.hidden_size()
        if current >= self.policy.max_hidden:
            return 0
        delta = max(16, int(current * self.policy.delta_frac))
        delta = min(delta, self.policy.max_hidden - current)
        before = brain.byte_size()
        brain.grow(delta)
        self._cooldown_left = self.policy.cooldown
        self.events.append(
            {
                "neurons_added": delta,
                "hidden": current + delta,
                "reason": reason,
                "bytes_after": brain.byte_size(),
            }
        )
        growth_bytes = self.events[-1]["bytes_after"] - before
        print(
            f"    GROWTH +{delta} neurons -> hidden {current + delta} "
            f"(brain +{growth_bytes:,} B)  [{reason}]"
        )
        return delta
