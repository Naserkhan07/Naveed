# NeuralCore — capability per byte, with zero external memory

An answering system that **is** its knowledge. No fact database, no vector
store, no knowledge graph, no RAG, no retrieval. Experience changes the
neural system itself; the only artifact is a single brain file.

**The goal is not "a file with no readable sentences" — it never had those.
The goal is: how much learned capability fits in how few bytes, and how far
can we compress before capability breaks?** (`neuralcore/compression.py`
measures exactly that; results below.)

## THE LOOP (implemented, `neuralcore/loop.py`)

```
1 EXPERIENCE           text / events land on the system
2 REPRESENTATION       holographic binding over shared vectors
3 INTERNAL STATE       State(t) -> experience -> State(t+1)
4 PREDICT / REASON     dynamics produce an activation
5 NEW EXPERIENCE       the system's OWN confident-correct prediction
                       re-enters as experience (self-affirmation);
                       the experience also evolves State(t+1)
6 PLASTICITY           error-driven change; important synapses stabilize,
                       useful capacity stays plastic
7 CONSOLIDATE          block-level importance promotion + sleep
8 TEST ON UNSEEN       never-trained probes
        GENERALIZATION?
        YES -> increase scale      NO -> modify architecture -> re-learn
        repeat
```

The stage-8 decision node is real code: mid-stream it tests only probes
built from knowledge acquired *so far* (never trained on), and its verdict
drives the flowchart — `scale_up` grows the experience stream;
`modify_architecture` strengthens stabilization (gate_lambda) and re-learns
the block. Run the whole flowchart:

```bash
python3 -m neuralcore.loop
```

```
  gate after A: scale_up (1.00)     <- unseen-probe capability
  gate after B: scale_up (1.00)
  gate after C: scale_up (1.00)
  gate after D: scale_up (1.00)
loop complete: capability 0.95, brain 141 KB
```

## Compression frontier (the reframed goal, measured)

`python3 -m neuralcore.compression` — capability is defined as
`0.5·retention + 0.25·paraphrase + 0.25·composition` on never-trained
probes.

**Size axis** — same curriculum, shrinking brains:

| brain | params | bytes | capability |
|---|---|---|---|
| nano | 9,360 | 84,648 | 0.66 *(interference-limited)* |
| compressed | 16,576 | 141,513 | 0.88 |
| **mid** | **37,152** | **299,624** | **0.95** ← minimal brain at full capability |
| full | 262,912 | 1,983,883 | 0.95 *(over-provisioned: 7× bigger, zero gain)* |

**Prune axis** — post-hoc compression of the trained compressed brain:

| synapses pruned | live weights | bytes | capability |
|---|---|---|---|
| 0% | 16,576 | 141,513 | 0.88 |
| 20% | 13,261 | 132,381 | **0.92** *(pruning regularizes)* |
| 40% | 9,946 | 121,542 | 0.92 |
| 60% | 6,631 | 109,429 | 0.88 |
| 70% | 4,973 | 102,821 | 0.83 |
| 90% | 1,658 | 88,510 | **0.22** ← the cliff |

Knowledge does not fade with compression — it holds a plateau (60% of
synapses removed at zero loss, even improving at 20–40%) and then cliffs.
The continual-learning scheduler exists precisely to push that plateau
wider: it is what lets a *small* brain keep old knowledge while new
knowledge arrives.

## Continual learning (A→B→C→D, sequential, no replay)

Capacity-pressured regime (16.6k live weights):

| | A | B | C | D | paraphrase |
|---|---|---|---|---|---|
| naive plasticity | 0.92→0.42 | 0.83→0.67 | 0.83→0.75 | 1.00 | 0.88 |
| + scheduler | 0.92→0.75 | 0.83→0.83 | 0.83→0.83 | 1.00 | **1.00** |

Naive forgetting on A: **+50%**. Scheduler: **+16.7%**, with zero forgetting
on B and C. An over-provisioned control (`--size full`) forgets nothing —
forgetting is a capacity-pressure phenomenon, which is why the compression
frontier above and the scheduler are one research question, not two.

Mechanism (`neuralcore/scheduler.py`): during a block, every synapse
accumulates the squared magnitude of its own proposed changes; at block end
"kept trying to move" = "load-bearing". Next block, plasticity is scaled by
`g = 1/(1+λ·ω/mean(ω))`. Nothing frozen, nothing listed; importance is
re-measured after every block and relaxed during sleep.

## Generalization vs memorization (never-trained probes)

- **Paraphrase** — 100%: `what is heated by the sun?` → water;
  `what heats the water?` → sun (the learned *inverse* direction).
- **Composition** — 100%: `sun --heats→ water --becomes→ steam --is→ hot`,
  each hop fed by the network's own previous output.
- **Unseen combinations** — honest refusal or structural residue
  (`fire --heats→` → "hot"), never a confident fabrication.

## The zero-external-memory guarantee

`tests/test_zero_memory.py`: after training the system is one ~140 KB file;
a process given only that file answers correctly; the raw bytes contain no
sentences and no fact records; unexperienced things get "I don't know".
External memory: **0 bytes, always** — including in every compression run.

## Talk to the brain

```bash
python3 -m neuralcore.experiments --out neuralcore_output
python3 -m neuralcore.chat neuralcore_output/brain-consolidation.ncb
#   what does the fire burn?   -> wood
#   what heats the water?      -> sun
#   what becomes steam?        -> water
python3 -m neuralcore.chat neuralcore_output/brain-consolidation.ncb \
        --chain "sun heats|becomes|is"
#   sun --heats--> water --becomes--> steam --is--> hot
```

## Status (the [1]–[14] plan)

1. ✅ No hidden fact/knowledge lookup — nothing to find; enforced by tests
2. ✅ Distributed representations — holographic binding + shared sparse hidden layer (overlap ≈ 0.10)
3. ✅ Persistent internal neural state — State(t) in the brain file
4. ✅ Adaptive plasticity — segment-wise importance, per-synapse gates, sleep relaxation, confidence-gated self-affirmation
5. ✅ A→B→C→D continual test — naive +50% forgetting vs scheduler +16.7%
6. ✅ Genuinely new combinations — honest-refusal scoring
7. ✅ Knowledge recovered with zero readable facts — byte-level + isolated-process tests
8. ✅ Information/compression measured — size axis + prune axis + cliff map (this is now the primary goal)
9. ⬜ Progressively larger knowledge — scale the curriculum
10. ⬜ LANGUAGE — learn facts from text instead of oracle tuples (`docs/ROADMAP.md` Phase 5)
11. ⬜ VISION — image → representation → shared state (Phase 5b)
12. ⬜ MULTIMODAL KNOWLEDGE (Phase 5c)
13. ⬜ SMALL GPT EXPERIMENT — strip a ~35M LM's learning/output stack, keep the trunk as perception substrate, insert this architecture (Phase 6)
14. ⬜ TRAIN → DELETE DATASET → TEST — the end experiment (Phase 6–7; the deletion test already exists at toy scale)

## Layout

```
neuralcore/
├── loop.py           THE LOOP — stages 1-8 + generalization decision node
├── compression.py    capability per byte: size axis + prune axis + frontier
├── hrr.py            unitary holographic reduced representations
├── perception.py     tokens, lemmas, emerging vocabulary (sensory cortex)
├── state.py          recurrent internal state
├── network.py        sparse predictive network, local error-driven plasticity
├── scheduler.py      metaplastic importance + protection gates
├── consolidation.py  sleep: importance relaxation + dead-synapse pruning
├── curriculum.py     experience blocks + never-trained probe families
├── output.py         query encoding + cleanup decoding + question parser
├── metrics.py        retention / forgetting / paraphrase / composition
├── experiments.py    the A→B→C→D experiment (naive vs scheduler)
├── chat.py           the answering bot — one brain file, nothing else
└── tests/            28 tests, incl. zero-external-memory guarantees
```

## Honest limitations

- Literal 0 bytes is unphysical; the measured target is **zero external
  memory** while shrinking internal state — exactly what the frontier above
  quantifies.
- Toy scale (24 facts, 73 concepts, hand-rolled question forms). The parser
  is linguistic scaffolding, deleted in Phase 10.
- Retention under pressure is +16.7%, not zero. Next mechanisms:
  importance-guided data-free reactivation during sleep, per-neuron
  metaplastic thresholds.

## Reproducing

```bash
python3 -m pytest neuralcore/tests/ -q            # all 28 guarantees
python3 -m neuralcore.loop                        # the flowchart, live
python3 -m neuralcore.experiments                 # naive vs scheduler
python3 -m neuralcore.compression                 # the frontier
python3 -m neuralcore.experiments --size full     # over-provisioned control
```

Deterministic per seed (`--seed`). Reports: `neuralcore_output/*.json`.
