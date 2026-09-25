"""CURRICULUM: the experiences, and the probes that separate
MEMORIZATION from GENERALIZATION from COMPOSITION (manifesto section 4).

Trained sets A-D are sequential experience blocks. The probe families are
NEVER trained:

  paraphrase probes   — known facts asked through unseen question forms
                        (representation robustness, not new inference)
  unseen combinations — (entity, relation) pairs never experienced together
                        (structural reuse; scored honestly, including
                        'declined' when the system asserts nothing)
  composition chains  — multi-hop queries where each hop feeds the next
                        through the network's own outputs
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .perception import Experience

# Four sequential experience blocks — the "Learn A, Learn B, Learn C, Learn D" test.
SETS: dict[str, list[tuple[str, str, str]]] = {
    "A": [  # physical world
        ("sun", "heats", "water"),
        ("fire", "burns", "wood"),
        ("ice", "cools", "drink"),
        ("wind", "moves", "leaves"),
        ("rain", "wets", "soil"),
        ("cold", "freezes", "water"),
    ],
    "B": [  # living world
        ("bird", "has", "wings"),
        ("fish", "has", "fins"),
        ("tree", "has", "roots"),
        ("bird", "can", "fly"),
        ("fish", "can", "swim"),
        ("worm", "lives", "soil"),
    ],
    "C": [  # people and work
        ("farmer", "grows", "rice"),
        ("baker", "makes", "bread"),
        ("smith", "forges", "steel"),
        ("doctor", "treats", "patient"),
        ("author", "writes", "books"),
        ("builder", "builds", "houses"),
    ],
    "D": [  # cycles, transformations, properties
        ("water", "becomes", "steam"),
        ("steam", "is", "hot"),
        ("ice", "is", "cold"),
        ("day", "follows", "night"),
        ("night", "follows", "day"),
        ("seed", "becomes", "tree"),
    ],
}

# Full-predicate surface forms for the inverse direction of each relation.
# (Cosmetic: the neural encoding uses the structured event, not the string.)
INVERSE_PHRASES: dict[str, str] = {
    "heats": "is heated by",
    "burns": "is burned by",
    "cools": "is cooled by",
    "moves": "is moved by",
    "wets": "is wetted by",
    "freezes": "is frozen by",
    "has": "belongs to",
    "can": "is a capacity of",
    "lives": "is lived in by",
    "grows": "is grown by",
    "makes": "is made by",
    "forges": "is forged by",
    "treats": "is treated by",
    "writes": "are written by",
    "builds": "are built by",
    "becomes": "comes from",
    "is": "is a property of",
    "follows": "is followed by",
}


@dataclass
class Curriculum:
    epochs_per_set: int = 12
    bidirectional: bool = True

    def set_experiences(self, set_name: str) -> list[Experience]:
        """One pass through a block. Bidirectional: every fact is experienced
        from both ends, so relations can be probed in either direction."""
        exps: list[Experience] = []
        for s, r, o in SETS[set_name]:
            exps.append(
                Experience(sentence=f"the {s} {r} the {o}.", subject=s, relation=r, object=o)
            )
            if self.bidirectional:
                inv_phrase = INVERSE_PHRASES.get(r, "relates to")
                exps.append(
                    Experience(
                        sentence=f"the {o} {inv_phrase} the {s}.",
                        subject=o,
                        relation=f"inv_{r}",
                        object=s,
                    )
                )
        return exps

    def set_names(self) -> list[str]:
        return list(SETS.keys())


@dataclass
class Probes:
    paraphrase: list[dict] = field(default_factory=list)
    unseen_combos: list[dict] = field(default_factory=list)
    chains: list[dict] = field(default_factory=list)


def build_probes() -> Probes:
    """Probes that are NEVER trained — they test sections 2-4 of the manifesto."""
    return Probes(
        paraphrase=[
            {"query": ("sun", "heats"), "expect": "water", "surface": "what is heated by the sun?"},
            {"query": ("water", "inv_heats"), "expect": "sun", "surface": "what heats the water?"},
            {"query": ("fire", "burns"), "expect": "wood", "surface": "what does the fire burn?"},
            {"query": ("bird", "can"), "expect": "fly", "surface": "what can the bird do?"},
            {"query": ("fish", "has"), "expect": "fins", "surface": "what does the fish have?"},
            {"query": ("baker", "makes"), "expect": "bread", "surface": "what is made by the baker?"},
            {"query": ("smith", "forges"), "expect": "steel", "surface": "what does the smith forge?"},
            {"query": ("steam", "inv_becomes"), "expect": "water", "surface": "what becomes steam?"},
        ],
        unseen_combos=[
            {"query": ("fire", "heats"), "surface": "what does the fire heat?"},
            {"query": ("sun", "burns"), "surface": "what does the sun burn?"},
            {"query": ("steam", "can"), "surface": "what can the steam do?"},
            {"query": ("farmer", "has"), "surface": "what does the farmer have?"},
            {"query": ("tree", "becomes"), "surface": "what does the tree become?"},
        ],
        chains=[
            {
                "surface": "the sun heats water -> water becomes ? -> steam is ?",
                "hops": [("sun", "heats", "water"), ("water", "becomes", "steam"), ("steam", "is", "hot")],
            },
            {
                "surface": "a seed becomes a tree -> a tree has ?",
                "hops": [("seed", "becomes", "tree"), ("tree", "has", "roots")],
            },
            {
                "surface": "day follows night -> night follows ?",
                "hops": [("day", "follows", "night"), ("night", "follows", "day")],
            },
        ],
    )
