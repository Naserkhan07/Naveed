# Roadmap — from this toy to the final experiment

Status: **Phase 1–4 complete at toy scale** (this repository). Each phase
below states what exists, what is added, and how it is measured.

---

## Phase 1 — CORE MECHANISM ✅ (done)

- Neural state: `state.py` — State(t) → experience → State(t+1), leaky,
  normalized, carried inside the brain file.
- Online experience: every update is one experience landing on the current
  state; no batch replay, no optimizer history.
- Plasticity: local error-driven updates (`network.py`).
- No external memory: enforced by test (`tests/test_zero_memory.py`).

## Phase 2 — KNOWLEDGE ✅ (done, toy scale)

- Multiple concepts: 73 emerging vocabulary concepts.
- Distributed representations: holographic bindings + sparse shared hidden
  layer (measured overlap ≈ 0.10).
- Compositional learning: bidirectional facts, multi-hop chains.
- Long-term retention: scheduler (Phase 3) holds A at 3× better than naive.

## Phase 3 — CONTINUAL LEARNING ✅ (done, toy scale) / ⬜ scale

- Sequential experiences A→B→C→D, no replay.
- New knowledge learned (D = 1.00) while old knowledge retained
  (A: +8.3% forgetting vs naive +25.0% under compression).
- Adaptive plasticity: importance re-measured per block; sleep relaxes it.
- ⬜ Scale-up targets: importance-guided data-free reactivation during sleep,
  per-neuron metaplastic thresholds, harder curricula (100+ facts).

## Phase 4 — GENERALIZATION ✅ (begun)

- Unseen combinations: honest-refusal scoring in place.
- Multi-step reasoning: composition chains 100% at toy scale.
- ⬜ Transfer: train relation structure in one domain, test in another.
- ⬜ Distinguish memorization vs generalization statistically
  (train/test splits over fact combinations, not just probes).

## Phase 5 — LANGUAGE ⬜

Replace the toy parser with learned perception:

1. Tokens → learned embeddings (the emerging vocabulary generalizes to
   subwords).
2. Sentences → experience streams through the recurrent state; the predictive
   network learns next-experience dynamics (a small LM objective emerges).
3. Facts are no longer (s, r, o) tuples given by an oracle — they must be
   *read out of* text. Probe: learn "The sun heats water" from a story,
   answer questions about it later.
4. The question-form priors in `output.py` (`_R_CAN`, `_R_PASSIVE`, …) are
   explicitly linguistic scaffolding to be deleted in this phase.

## Phase 6 — SCALE ⬜ (the 35M transplant lives here)

The final experiment, concretely:

1. Take a small pretrained LM (~35M params, e.g. a GPT-style model).
2. **Remove its learning architecture**: strip the training-time objective
   head(s) and the optimizer-trained output pathway; keep the transformer
   trunk as a *perception/dynamics substrate* — its residual stream becomes
   the internal state interface State(t) of this architecture.
3. **Insert our architecture**: HRR read/write projections between the trunk
   and the sparse predictive network; metaplastic scheduler over the
   combined parameters; sleep/consolidation after each corpus block.
4. Train on a large corpus as a continual experience stream (sequential
   blocks, no global shuffling replay).
5. **Delete / archive the corpus.**
6. Measure, from the brain alone:
   - capability remaining (perplexity, QA accuracy vs the original LM),
   - minimum viable parameter count,
   - forgetting curves across corpus blocks,
   - generalization on held-out compositions,
   - information density (bits of reusable capability per parameter).

Honest expectations: we do **not** assume a 35M model collapses to a literal
0B system. Physics requires some physical state to carry memory. The
experiment quantifies how *small* the state can get while external memory
stays exactly zero.

## Phase 7 — COMPRESSION ⬜

- Prune (exists: sleep prunes dead synapses), then quantize brain files
  (int8/dynamic), then architecturally shrink until interference reappears —
  at which point Phase 3's scheduler is what preserves capability.
- Measure information density at each step: capability / persistent bytes.

## FINAL EXPERIMENT

```
training data   → deleted
external memory → none      (0 files)
RAG             → none
fact storage    → none
                         ↓
        a small neural system that still answers
```

This repository is the end-to-end miniature of that experiment, including
the deletion test — `tests/test_zero_memory.py` copies the brain into an
empty directory and verifies it answers from weights alone.
