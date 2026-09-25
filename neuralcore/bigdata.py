"""LARGE-SCALE EXPERIENCE — a procedurally generated knowledge stream.

Builds a big sequential experience corpus (thousands of facts over many
domains), plus held-out probe families that are NEVER trained:

  retention   trained facts, re-asked (both the fact and its block context)
  unseen      (entity, relation) pairs never experienced — expect refusal
  chains      multi-hop traversals of trained transformation facts
  reuse       structural-reuse signal: when an unseen pair does activate,
              does the answer at least come from the subject's own domain?

The corpus size is parametric — the same generator emits 100 facts or 1M
facts; the sandbox hardware decides what we can stream in a demo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .perception import normalize_word

# Domain vocabularies. Every word must pass the perception layer's normalizer
# unchanged (validated at build time), so concept keys are stable.
DOMAIN_WORDS: dict[str, list[str]] = {
    "mineral": [
        "marble", "quartz", "basalt", "granite", "slate", "gypsum", "flint",
        "mica", "beryl", "topaz", "garnet", "olivine", "pyrite", "zircon",
        "halite", "dolomite", "feldspar", "hematite", "azurite", "obsidian",
        "pumice", "scoria", "breccia", "sandstone", "mudstone", "limestone",
        "chalk", "shale", "schist", "eclogite", "perlite", "malachite",
    ],
    "metal": [
        "iron", "zinc", "gold", "indium", "platinum", "titanium", "cobalt",
        "nickel", "chrome", "tungsten", "uranium", "radium", "calcium",
        "sodium", "potassium", "magnesium", "aluminum", "mercury", "osmium",
        "iridium", "palladium", "rhodium", "cadmium", "bismuth", "antimony",
        "arsenic", "lithium", "cesium", "strontium", "barium", "zirconium",
        "manganese",
    ],
    "plant": [
        "cedar", "oak", "fern", "moss", "ivy", "pine", "birch", "willow",
        "bamboo", "cycad", "vetch", "thistle", "tamarack", "mahogany",
        "redwood", "spruce", "hickory", "sycamore", "magnolia", "jasmine",
        "hyssop", "rosemary", "sage", "basil", "thyme", "alfalfa",
        "sorghum", "millet", "barley", "oat", "wheat", "maize",
    ],
    "creature": [
        "fox", "wolf", "eagle", "owl", "salmon", "raven", "heron", "toad",
        "elk", "lynx", "falcon", "sparrow", "pigeon", "rabbit", "weasel",
        "ferret", "gerbil", "gecko", "iguana", "python", "cobra", "viper",
        "trout", "perch", "pike", "marlin", "orca", "dolphin", "manatee",
        "leopard", "cheetah", "gazelle",
    ],
    "water": [
        "tide", "mist", "foam", "current", "icefield", "lagoon", "marsh",
        "brook", "creek", "basin", "channel", "pond", "puddle", "rivulet",
        "waterfall", "whirlpool", "delta", "fjord", "strait", "bayou",
        "wetland", "upland", "monsoon", "drizzle", "dew", "frost", "hail",
        "sleet", "blizzard", "drought", "estuary", "sound",
    ],
    "sky": [
        "storm", "cloud", "tempest", "wind", "fog", "aurora", "comet",
        "meteor", "eclipse", "horizon", "zenith", "nebula", "pulsar",
        "quasar", "galaxy", "planet", "asteroid", "meteorite", "zodiac",
        "orbit", "vacuum", "gravity", "twilight", "dawn", "dusk", "shadow",
        "rainbow", "mirage", "zephyr", "cyclone", "hurricane", "tornado",
    ],
}

# Relations, grouped by how they compose. "becomes" facts form the chains.
GLOBAL_RELATIONS = [
    "heats", "melts", "freezes", "dissolves", "attracts", "repels",
    "conducts", "absorbs", "emits", "reflects", "contains", "supports",
    "produces", "consumes", "connects", "shields", "becomes",
]

N_RELATIONS_PER_DOMAIN = 8


@dataclass
class Corpus:
    facts: list[tuple[str, str, str]]            # the experience stream (ordered)
    blocks: list[list[int]]                      # block -> fact indices
    domain_of: dict[str, str] = field(default_factory=dict)
    chains: list[list[tuple[str, str, str]]] = field(default_factory=list)
    train_pairs: set[tuple[str, str]] = field(default_factory=set)

    def summary(self) -> str:
        n_entities = len(self.domain_of)
        n_domains = len(set(self.domain_of.values()))
        n_relations = len({normalize_word(r) for _, r, _ in self.facts})
        return (
            f"{len(self.facts)} facts, {n_entities} entities, {n_domains} domains, "
            f"{n_relations} relations, {len(self.blocks)} sequential blocks, "
            f"{len(self.chains)} chains"
        )


def build_corpus(
    seed: int = 0,
    facts_per_domain: int = 224,
    chains_per_domain: int = 10,
    n_blocks: int = 16,
    n_relations_per_domain: int = N_RELATIONS_PER_DOMAIN,
) -> Corpus:
    """Generate the stream. 'becomes' chains give the world compositional
    structure; everything else is many-to-many association within a domain."""
    rng = np.random.default_rng(seed)

    # validate vocabularies against the perception layer
    for domain, words in DOMAIN_WORDS.items():
        for w in words:
            if normalize_word(w) != w:
                raise ValueError(f"corpus word fails normalization: {w!r} -> {normalize_word(w)!r}")

    facts: list[tuple[str, str, str]] = []
    blocks: list[list[int]] = []
    domain_of: dict[str, str] = {}
    chains: list[list[tuple[str, str, str]]] = []
    train_pairs: set[tuple[str, str]] = set()

    domains = list(DOMAIN_WORDS.keys())
    rel_per_domain: dict[str, list[str]] = {}
    for domain in domains:
        words = DOMAIN_WORDS[domain]
        for w in words:
            domain_of[w] = domain
        idx = rng.choice(len(GLOBAL_RELATIONS), size=min(n_relations_per_domain, len(GLOBAL_RELATIONS)), replace=False)
        rels = [GLOBAL_RELATIONS[i] for i in idx]
        if "becomes" not in rels:
            rels[0] = "becomes"
        rel_per_domain[domain] = rels

    for domain in domains:
        words = DOMAIN_WORDS[domain]
        rels = [normalize_word(r) for r in rel_per_domain[domain]]
        domain_facts: list[tuple[str, str, str]] = []

        # compositional chains: a -becomes-> b -becomes-> c
        chain_words = list(rng.choice(words, size=chains_per_domain * 3, replace=False))
        for i in range(chains_per_domain):
            a, b, c = chain_words[3 * i: 3 * i + 3]
            for s, o in ((a, b), (b, c)):
                fact = (s, "become", o)
                if fact not in domain_facts:
                    domain_facts.append(fact)
                    chains.append([(a, "become", b), (b, "become", c)])

        # ordinary association facts with unique (subject, relation) pairs
        remaining = facts_per_domain - len(domain_facts)
        used_pairs: set[tuple[str, str]] = {(s, r) for s, r, _ in domain_facts}
        guard = 0
        while len(domain_facts) < facts_per_domain and guard < 100_000:
            guard += 1
            s = words[int(rng.integers(len(words)))]
            r = rels[int(rng.integers(len(rels)))]
            o = words[int(rng.integers(len(words)))]
            if o == s or (s, r) in used_pairs:
                continue
            used_pairs.add((s, r))
            domain_facts.append((s, r, o))

        for fact in domain_facts:
            train_pairs.add((fact[0], fact[1]))
            facts.append(fact)

    # sequential blocks: domains appear in order (later = newer experience),
    # each block mixing the next chunk of each domain's facts
    per_block = max(1, len(facts) // n_blocks)
    domain_facts: dict[str, list[tuple[str, str, str]]] = {d: [] for d in domains}
    for f in facts:
        domain_facts[domain_of[f[0]]].append(f)
    # interleave round-robin so each block contains one chunk of one domain,
    # cycling domains — a chronological stream where domains arrive in waves
    queues = {d: list(reversed(fs)) for d, fs in domain_facts.items()}
    order = []
    active = [d for d in domains if queues[d]]
    while any(queues[d] for d in domains):
        for d in domains:
            if queues[d]:
                take = min(per_block // 2 + 1, len(queues[d]))
                chunk = [queues[d].pop() for _ in range(take)]
                order.extend(chunk)
                if len(order) - len(blocks) * per_block >= per_block or not any(queues.values()):
                    pass
    facts = order
    blocks = [list(range(i, min(i + per_block, len(facts)))) for i in range(0, len(facts), per_block)]
    return Corpus(facts=facts, blocks=blocks, domain_of=domain_of, chains=chains, train_pairs=train_pairs)


@dataclass
class ScaleProbes:
    retention: list[tuple[str, str, str]]
    unseen: list[tuple[str, str]]                 # (subject, relation) never paired
    chains: list[list[tuple[str, str, str]]]
    unseen_domain: dict[tuple[str, str], str]     # for the structural-reuse signal


def build_scale_probes(corpus: Corpus, seed: int = 1, n_retention: int = 300,
                       n_unseen: int = 200, n_chains: int = 20) -> ScaleProbes:
    rng = np.random.default_rng(seed)
    domains = list(DOMAIN_WORDS.keys())

    idx = rng.choice(len(corpus.facts), size=min(n_retention, len(corpus.facts)), replace=False)
    retention = [corpus.facts[int(i)] for i in idx]

    rel_by_domain: dict[str, list[str]] = {d: [] for d in domains}
    for s, r, _ in corpus.facts:
        d = corpus.domain_of[s]
        if r not in rel_by_domain[d]:
            rel_by_domain[d].append(r)

    unseen, unseen_domain = [], {}
    guard = 0
    while len(unseen) < n_unseen and guard < 100_000:
        guard += 1
        d = domains[int(rng.integers(len(domains)))]
        words = DOMAIN_WORDS[d]
        s = words[int(rng.integers(len(words)))]
        rels = rel_by_domain[d]
        r = rels[int(rng.integers(len(rels)))]
        if (s, r) in corpus.train_pairs or (s, r) in unseen_domain:
            continue
        unseen.append((s, r))
        unseen_domain[(s, r)] = d

    chain_idx = rng.choice(len(corpus.chains), size=min(n_chains, len(corpus.chains)), replace=False)
    chains = [corpus.chains[int(i)] for i in chain_idx]

    return ScaleProbes(retention=retention, unseen=unseen, chains=chains, unseen_domain=unseen_domain)


def eval_facts(brain, facts: list[tuple[str, str, str]]) -> tuple[float, float]:
    """Accuracy + mean confidence of trained facts (sampled retention)."""
    from .output import ask

    correct, conf = 0, 0.0
    for s, r, o in facts:
        ans = ask(brain, s, r)
        conf += ans.confidence
        correct += int(ans.concept == normalize_word(o))
    return correct / max(1, len(facts)), conf / max(1, len(facts))


def eval_unseen(brain, probes: ScaleProbes, refusal_threshold: float = 0.45) -> dict:
    """Refusal rate on never-experienced pairs + the structural-reuse signal:
    when the system does answer, does the answer come from the subject's own
    domain more often than chance?"""
    from .output import ask

    domains = list(DOMAIN_WORDS.keys())
    refused, answered, domain_match = 0, 0, 0
    for s, r in probes.unseen:
        ans = ask(brain, s, r)
        if ans.confidence < refusal_threshold or ans.concept is None:
            refused += 1
            continue
        answered += 1
        got_domain = probes.unseen_domain.get((s, r))
        if got_domain and ans.concept in DOMAIN_WORDS.get(got_domain, []):
            domain_match += 1
    chance = 1.0 / len(domains)
    total = max(1, len(probes.unseen))
    return {
        "refusal_rate": refused / total,
        "answered": answered,
        "domain_match_rate": (domain_match / answered) if answered else 0.0,
        "chance": chance,
        "n_probes": len(probes.unseen),
    }


def eval_chains(brain, chains: list[list[tuple[str, str, str]]]) -> tuple[float, list[dict]]:
    """Multi-hop traversal: each hop's answer feeds the next hop's subject."""
    from .output import ask

    results, correct = [], 0
    for chain in chains:
        ok, trace, entity = True, [], None
        for i, (s, r, expected) in enumerate(chain):
            subj = s if i == 0 else entity
            ans = ask(brain, subj, r)
            hop_ok = ans.concept == normalize_word(expected)
            ok = ok and hop_ok
            trace.append({"q": f"{subj}/{r}", "got": ans.concept, "ok": hop_ok})
            entity = ans.concept if hop_ok else expected
        correct += int(ok)
        results.append({"hops": trace, "ok": ok})
    return correct / max(1, len(chains)), results
