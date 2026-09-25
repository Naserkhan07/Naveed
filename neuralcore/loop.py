"""THE LOOP — the full experience cycle, as a running engine.

    1 EXPERIENCE            text / events land on the system
    2 NEURAL REPRESENTATION holographic binding over shared vectors
    3 INTERNAL STATE        State(t) -> experience -> State(t+1)
    4 PREDICT / REASON      dynamics produce an activation
    5 NEW EXPERIENCE        the system's OWN prediction re-enters the loop
                            (confidence-gated self-affirmation: being right
                            is itself an experience that consolidates)
    6 PLASTICITY UPDATE     error-driven change; important synapses are
                            stabilized, useful capacity stays plastic
    7 CONSOLIDATE           block-level importance promotion + sleep
    8 TEST ON UNSEEN        never-trained probes

            GENERALIZATION?
             /            \
           YES             NO
            ↓               ↓
     increase scale   modify architecture
            └───────┬───────┘
                    ↓
             repeat learning
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .brain import Brain, BrainConfig
from .compression import capability_score
from .consolidation import sleep
from .curriculum import Curriculum, probes_for_sets
from . import metrics

LEARNING_RATE = 0.1
DEFAULT_CONFIG = BrainConfig(dim=64, hidden=128, sparsity_k=24, gate_lambda=15.0)


@dataclass
class StepReport:
    confidence: float
    affirmed: bool      # stage 5 fired: prediction re-entered as experience


@dataclass
class BlockReport:
    set_name: str
    epochs: int
    mean_confidence: float
    affirm_rate: float
    final_confidence: float = 0.0   # last-pass confidence: the growth signal


@dataclass
class LoopDecision:
    stage: int
    action: str         # "scale_up" | "modify_architecture" | "complete"
    generalization: float
    reason: str


@dataclass
class LoopReport:
    blocks: list[BlockReport] = field(default_factory=list)
    decisions: list[LoopDecision] = field(default_factory=list)
    capability: float = 0.0
    final: dict[str, float] = field(default_factory=dict)


class NeuralLoop:
    """One living system moving through the 8 stages, forever."""

    def __init__(
        self,
        brain: Brain,
        self_affirm_weight: float = 0.15,
        affirm_threshold: float = 0.60,
        log=None,
    ):
        self.brain = brain
        self.affirm_weight = self_affirm_weight
        self.affirm_threshold = affirm_threshold
        self.log = log or (lambda *a, **k: None)
        self.curriculum = Curriculum()

    # -- stages 1-6: one experience -----------------------------------------

    def experience_step(self, subject: str, relation: str, target_vec: np.ndarray, lr: float) -> StepReport:
        brain = self.brain
        perc = brain.perceiver()

        # stage 2: representation
        x_repr = perc.encode_event(subject, relation, "?")

        # stage 3: internal state — State(t) is the CONTEXT prediction sees
        # (manifesto §6: State(t) -> experience(t) -> State(t+1)); the
        # experience then evolves the state for whatever comes next (stage 5)
        x = perc.encode_query(subject, relation, state_h=brain.state.h)

        # stage 4: predict
        y = brain.net.forward(x)
        conf = brain.space.cosine(y, target_vec)

        # stage 6: plasticity — error-driven, adaptively gated
        upd = brain.net.compute_update(x, target_vec)
        upd.scale(lr)
        brain.scheduler.observe(upd)
        brain.net.apply_update(brain.scheduler.protect(upd))

        # stage 5: the system's own successful prediction re-enters as
        # experience. Only when the dynamics are already confident-correct:
        # being right consolidates; being wrong is handled by the error
        # above — never by self-deception.
        affirmed = False
        if self.affirm_weight > 0 and conf >= self.affirm_threshold:
            upd2 = brain.net.compute_update(x, target_vec)
            upd2.scale(lr * self.affirm_weight)
            brain.scheduler.observe(upd2)
            brain.net.apply_update(brain.scheduler.protect(upd2))
            affirmed = True

        # stage 5 (cont.): the experience flows into the recurrent state —
        # State(t+1) carries it into every future prediction
        brain.state.update(x_repr)

        return StepReport(confidence=conf, affirmed=affirmed)

    # -- stages 1-6 over a block of experience -------------------------------

    def live_block(self, set_name: str, epochs: int | None = None, lr: float = LEARNING_RATE) -> BlockReport:
        epochs = epochs or self.curriculum.epochs_per_set
        brain = self.brain
        exps = self.curriculum.set_experiences(set_name)
        confs, affirmed_count, steps = 0.0, 0, 0
        final_confidence = 0.0
        for epoch in range(epochs):
            brain.state.reset()
            epoch_confs, epoch_steps = 0.0, 0
            for exp in exps:
                target = brain.vocab.get(exp.object)   # emerging vocabulary grows here
                rep = self.experience_step(exp.subject, exp.relation, target, lr)
                confs += rep.confidence
                epoch_confs += rep.confidence
                affirmed_count += int(rep.affirmed)
                steps += 1
                epoch_steps += 1
            final_confidence = epoch_confs / max(1, epoch_steps)
        report = BlockReport(
            set_name=set_name,
            epochs=epochs,
            mean_confidence=confs / max(1, steps),
            affirm_rate=affirmed_count / max(1, steps),
            final_confidence=final_confidence,
        )
        self.log(
            f"  block {set_name}: mean confidence {report.mean_confidence:.2f} "
            f"(final pass {report.final_confidence:.2f}), "
            f"self-affirmation {report.affirm_rate:.0%} of steps"
        )
        return report

    # -- stage 7: consolidate -------------------------------------------------

    def consolidate(self) -> None:
        self.brain.scheduler.end_block()
        sleep(self.brain)

    # -- stage 8: test on unseen experience + the decision node ----------------

    def generalization_gate(self, known_sets: list[str], threshold: float = 0.80) -> LoopDecision:
        """Only probes built from knowledge acquired SO FAR count; the probes
        themselves were never trained (unseen experience)."""
        stage = 8
        probes = probes_for_sets(known_sets)
        para_acc, _ = metrics.evaluate_paraphrase(self.brain, probes=probes) if probes.paraphrase else (1.0, [])
        if probes.chains:
            comp_acc, _ = metrics.evaluate_composition(self.brain, probes=probes)
        else:
            comp_acc = 1.0   # no multi-hop structure acquired yet — nothing to fail

        score = 0.5 * para_acc + 0.5 * comp_acc
        if score >= threshold:
            return LoopDecision(
                stage=stage,
                action="scale_up",
                generalization=score,
                reason=f"unseen-probe capability {score:.2f} >= {threshold:.2f}: "
                "knowledge is structural — grow the experience stream",
            )
        return LoopDecision(
            stage=stage,
            action="modify_architecture",
            generalization=score,
            reason=f"unseen-probe capability {score:.2f} < {threshold:.2f}: "
            "dynamics are overwriting — strengthen stabilization and re-learn",
        )


def run_progressive_loop(
    config: BrainConfig | None = None,
    lr: float = LEARNING_RATE,
    gate_threshold: float = 0.80,
    max_retries: int = 1,
    log=None,
) -> tuple[Brain, LoopReport]:
    """The full flowchart: learn -> test on unseen -> YES: scale up /
    NO: modify architecture -> repeat — until the curriculum is exhausted."""
    log = log or (lambda *a, **k: None)
    brain = Brain.build(config or DEFAULT_CONFIG)
    loop = NeuralLoop(brain, log=log)
    report = LoopReport()

    set_names = Curriculum().set_names()
    known: list[str] = []
    for i, set_name in enumerate(set_names):
        known.append(set_name)
        report.blocks.append(loop.live_block(set_name, lr=lr))
        loop.consolidate()

        decision = loop.generalization_gate(known, threshold=gate_threshold)
        report.decisions.append(decision)
        log(f"  gate after {set_name}: {decision.action} ({decision.generalization:.2f})")

        retries = 0
        while decision.action == "modify_architecture" and retries < max_retries and i < len(set_names) - 1:
            # the architecture modification: strengthen stabilization, re-live
            # the block, consolidate again
            brain.scheduler.cfg.gate_lambda *= 1.5
            log(f"    modification: gate_lambda -> {brain.scheduler.cfg.gate_lambda:.1f}, re-learning {set_name}")
            report.blocks.append(loop.live_block(set_name, lr=lr))
            loop.consolidate()
            decision = loop.generalization_gate(known, threshold=gate_threshold)
            report.decisions.append(decision)
            retries += 1

    report.capability = capability_score(brain)
    report.final = metrics.evaluate_all(brain)
    log(f"loop complete: capability {report.capability:.2f}, final {report.final}")
    return brain, report


if __name__ == "__main__":
    import os

    def print_log(*a, **k):
        print(*a, **k)

    brain, rep = run_progressive_loop(log=print_log)
    print("\ndecision trail:")
    for d in rep.decisions:
        print(f"  stage {d.stage} after learning: {d.action:<20} generalization={d.generalization:.2f}")
    os.makedirs("neuralcore_output", exist_ok=True)
    print(f"\nbrain bytes: {brain.save('neuralcore_output/brain-loop.ncb'):,}")
