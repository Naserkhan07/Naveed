"""The answering bot — inference only.

This is the "no external memory" proof in daily use: the process loads ONE
brain file and nothing else. There is no database, no retrieval, no training
data on disk. Ask it what it lived through; it answers from its dynamics.

Run (after training):
    python -m neuralcore.chat neuralcore_output/brain-consolidation.ncb
    python -m neuralcore.chat neuralcore_output/brain-consolidation.ncb --ask "what does the fire burn?"
    python -m neuralcore.chat neuralcore_output/brain-consolidation.ncb --chain "sun heats|becomes|is"

REPL commands: :help  :state  :size  :quit
"""

from __future__ import annotations

import argparse
import os
import sys

from .brain import Brain
from .output import answer_surface, ask


def run_chain(brain: Brain, chain_spec: str) -> None:
    """Multi-hop composition: each hop's answer feeds the next hop's subject.

    Format: "sun heats|becomes|is" — the first segment is 'subject relation'
    (or just a starting entity), every later segment is a relation applied to
    the previous answer.
    """
    steps = [s.strip() for s in chain_spec.split("|") if s.strip()]
    head = steps[0].split()
    entity = head[0]
    relations = ([head[1]] if len(head) > 1 else []) + steps[1:]
    print(f"chain: start at '{entity}'")
    for rel in relations:
        ans = ask(brain, entity, rel)
        got = ans.concept or "?"
        print(f"  {entity} --{rel}--> {got}   (confidence {ans.confidence:.2f})")
        if ans.concept is None:
            print("  (chain ends: the dynamics went dark)")
            return
        entity = ans.concept


def repl(brain: Brain) -> None:
    print("NeuralCore — answering from neural dynamics only.")
    print("No database. No retrieval. Training data: deleted.")
    print("Try: what does the fire burn?   |   what heats the water?   |   :quit")
    while True:
        try:
            line = input("\nask> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in (":quit", ":q", "exit"):
            break
        if line == ":help":
            print("ask anything about what it experienced; ':state' state norm; ':size' brain bytes")
            continue
        if line == ":state":
            print(f"neural state |h| = {float(sum(brain.state.h**2)) ** 0.5:.3f}")
            continue
        if line == ":size":
            print(f"brain file would be {brain.byte_size():,} bytes")
            continue
        ans = answer_surface(brain, line)
        if ans is None or ans.concept is None:
            print("I don't know. (no learned dynamics for that)")
        else:
            print(f"{ans.concept}   (confidence {ans.confidence:.2f})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("brain", help="path to a .ncb brain file (the ONLY input)")
    ap.add_argument("--ask", default=None, help="ask one question and exit")
    ap.add_argument("--chain", default=None, help="demo multi-hop: 'sun heats|becomes|is'")
    args = ap.parse_args()

    if not os.path.exists(args.brain):
        sys.exit(f"brain file not found: {args.brain}\ntrain one: python -m neuralcore.experiments")

    brain = Brain.load(args.brain)  # nothing else is opened, ever
    if args.ask:
        ans = answer_surface(brain, args.ask)
        print("I don't know." if ans is None or ans.concept is None else ans.concept)
        return
    if args.chain:
        run_chain(brain, args.chain)
        return
    repl(brain)


if __name__ == "__main__":
    main()
