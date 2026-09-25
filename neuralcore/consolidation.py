"""SLEEP / consolidation.

After a block of experience the system 'sleeps':
  1. importance traces decay toward current relevance (softening protection
     for knowledge the network no longer leans on),
  2. near-dead synapses are pruned — compression toward a smaller brain,
     manifesto sections 7 and 15 (Phase 7 starts here, at toy scale).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SleepReport:
    pruned_synapses: int
    weights_before: int
    weights_after: int
    mean_omega: float


def sleep(brain, prune_threshold: float = 1e-6, omega_rho: float = 0.9) -> SleepReport:
    net, scheduler = brain.net, brain.scheduler
    scheduler.sleep(rho=omega_rho)

    before = net.parameter_count()
    pruned = 0
    for name, p in net.named_parameters().items():
        dead = (np.abs(p) < prune_threshold) & (scheduler.omega[name] < prune_threshold)
        pruned += int(np.count_nonzero(dead & (p != 0.0)))
        p[dead] = 0.0

    after = net.nonzero_parameter_count()
    mean_omega = float(np.mean([o.mean() for o in scheduler.omega.values()]))
    return SleepReport(
        pruned_synapses=pruned,
        weights_before=before,
        weights_after=after,
        mean_omega=mean_omega,
    )
