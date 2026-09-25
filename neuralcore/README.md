# NeuralCore — a neural knowledge system with no external memory

An answering system that **is** its knowledge. There is no fact database, no
vector store, no knowledge graph, no RAG, no retrieval. Experiences change
the neural system itself; afterwards, the only artifact is a single brain
file (`.ncb`). Delete everything else and it still answers.

This is the Phase 1–4 working reference implementation of the project
manifesto (perception → representation → neural dynamics → prediction →
output, continual learning, plasticity, distributed knowledge, zero external
memory at inference).

```
EXPERIENCE (text / events)
      ↓
PERCEPTION        tokenize + lemma  → emerging vocabulary activations
      ↓
REPRESENTATION    holographic binding (unitary HRR, dim 256)
      ↓
NEURAL DYNAMICS   recurrent internal state  +  sparse predictive network
      |           stateful, plastic, error-driven local learning
      ↓
PREDICTION        activation decoded by cleanup against the vocabulary
      ↓
OUTPUT            answer — or "I don't know" (never asserts from a table;
                  there is no table)
```

## Quick start

```bash
# 1. run the experiment: learn A→B→C→D sequentially, no replay
python3 -m neuralcore.experiments --out neuralcore_output

# 2. talk to the resulting brain — the ONLY input is the .ncb file
python3 -m neuralcore.chat neuralcore_output/brain-consolidation.ncb
#   try:  what does the fire burn?   what heats the water?
#         what becomes steam?        what can the bird do?
#   multi-hop: --chain "sun heats|becomes|is"

# 3. tests (includes the zero-external-memory guarantee)
python3 -m pytest neuralcore/tests/ -q
```

## What "memory" means here

Nothing looks like this:

```
question → database → retrieved fact → answer
```

The flow is:

```
experience → weight changes + state change → future experience
            activates learned dynamics     → behavior
```

`fire → burns → wood` is not stored anywhere. The network develops internal
representations and dynamics from which the answer *emerges* when queried.

## The continual learning result (manifesto §3)

Four experience blocks are learned strictly sequentially — learn A, then B,
then C, then D. No replay of old data. The default regime uses a
**capacity-compressed brain** (16,576 live weights) where interference is
real:

```
                    A        B        C        D      paraphrase
naive plasticity  0.92→0.67  0.83→0.58  0.83   1.00      0.75
+ scheduler       0.92→0.83  0.83→0.67  0.83   1.00      1.00

forgetting (A):   naive +25.0%   vs   scheduler +8.3%
```

Naive plasticity reproduces the V11-style decay (old answers literally drift
to wrong concepts — e.g. "what heats the water?" starts answering "night").
The metaplastic scheduler holds retention at ~3× better while still learning
every new block to the same level.

Mechanism (see `neuralcore/scheduler.py`): while a block of experience is
lived, every synapse accumulates the squared magnitude of its own proposed
changes. At block end, "kept trying to move" = "was load-bearing". During
the next block each synapse's plasticity is scaled by
`g = 1/(1+λ·ω/mean(ω))` — important connections resist change, fresh ones
stay fully plastic. **Nothing is frozen and nothing is listed; the network
re-measures importance after every block.** A control run with an
over-provisioned brain (`--size full`) shows near-zero forgetting even for
naive plasticity — demonstrating that forgetting is a capacity-pressure
phenomenon, which is exactly the regime the compression roadmap targets.

## Generalization vs memorization (manifesto §4)

Probes that are **never trained** (`neuralcore/curriculum.py`):

- **Paraphrase** — known facts through unseen question forms: 100%
  (`what is heated by the sun?` → water; `what heats the water?` → sun — the
  learned *inverse* direction).
- **Composition** — multi-hop chains where each hop feeds the next through
  the network's own outputs: 100%
  `sun --heats→ water --becomes→ steam --is→ hot`.
- **Unseen combinations** — (entity, relation) pairs never experienced
  together: the system mostly **declines** (confidence below threshold) or
  produces structurally-related activations (e.g. `fire --heats→` → "hot").
  Scored honestly: refusal counts as refusal, not as a hit.

## Distributed knowledge (manifesto §7)

Concepts are holographic bindings over shared vectors, and the sparse hidden
layer is shared: mean active-neuron overlap across concepts ≈ 0.10 (66
pairs) — the same neurons participate in many concepts, which is what makes
interference (and therefore the whole continual-learning problem) real, and
compression possible.

## The zero-external-memory guarantee (manifesto §9–10)

Enforced by `tests/test_zero_memory.py`:

1. after training, the system is **one file** (~140 KB compressed brain);
2. a process given **only** that file — in an empty directory — answers
   correctly (paraphrase + direct queries);
3. the raw bytes of the brain file contain **no sentences and no fact
   records** — knowledge exists only as weight geometry;
4. unexperienced things (`rocket`, `explodes`) are answered with
   "I don't know", never a confident hallucinated lookup.

Brain file contents: predictive weights, emerging vocabulary vectors (a
sensory cortex — symbol→activation mappings, zero facts), recurrent state,
synaptic importance traces, architecture config. Float32, no pickle.

## Layout

```
neuralcore/
├── hrr.py           REPRESENTATION — unitary holographic reduced representations
├── perception.py    PERCEPTION — tokens, lemmas, emerging vocabulary, encoding
├── state.py         internal state: State(t) → experience → State(t+1)
├── network.py       sparse predictive network, local error-driven plasticity
├── scheduler.py     metaplastic importance + protection gates (the retention mechanism)
├── consolidation.py sleep: importance relaxation + dead-synapse pruning
├── curriculum.py    experience blocks A–D + never-trained probe families
├── output.py        query encoding + cleanup decoding + toy question parser
├── metrics.py       retention / forgetting / paraphrase / composition / overlap
├── experiments.py   the A→B→C→D continual experiment (naive vs scheduler)
├── chat.py          the answering bot — loads one brain file, nothing else
└── tests/           19 tests, incl. the zero-external-memory guarantee
```

## Honest limitations (and where they go next)

- **Toy scale.** 24 facts, 73 concepts, a hand-rolled question-form parser.
  The parser is a *linguistic prior*, not knowledge; Phase 5 replaces it with
  learned language dynamics (see `docs/ROADMAP.md`).
- **Literal 0 bytes is not physical.** Any system that remembers anything
  carries information in some physical state. The meaningful target — and the
  one measured here — is: **zero external dataset, zero database, zero RAG,
  zero fact storage, zero training data retained**, while shrinking the
  internal state (here: 141 KB total; pruning already removes dead synapses
  during sleep).
- **Retention is not yet perfect** (+8.3% forgetting on A under compression).
  Sleep currently relaxes importance and prunes; it does not yet rehearse.
  The next mechanisms to test: importance-guided internal reactivation
  (generative, data-free) and per-neuron metaplastic thresholds.
- **The 35M-GPT transplant is Phase 6–7**, not this repository. The transplant
  plan — remove the LM's learning/output stack, keep the residual stream as
  our state interface, attach this architecture, train, delete the corpus —
  is written up in `docs/ROADMAP.md` with its measurement plan.

## Reproducing

```bash
python3 -m neuralcore.experiments --out neuralcore_output              # compressed regime
python3 -m neuralcore.experiments --size full --out neuralcore_output  # over-provisioned control
python3 -m pytest neuralcore/tests/ -q                                 # all guarantees
```

Everything is deterministic per seed (`--seed`). Reports are written to
`neuralcore_output/report-*.json`.
