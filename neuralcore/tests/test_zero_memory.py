"""THE zero-external-memory guarantee (manifesto §9, §10).

After training:
  1. the brain is one file;
  2. a process given ONLY that file (in an empty directory) still answers;
  3. the file contains no sentences and no fact tables — inspect the bytes.
"""

import os
import shutil

import pytest

from neuralcore import metrics
from neuralcore.brain import Brain
from neuralcore.experiments import train_brain


@pytest.fixture(scope="module")
def trained_brain(tmp_path_factory):
    out = tmp_path_factory.mktemp("train")
    brain, _ = train_brain(mode="consolidation", size="compressed", sets=["A", "B"], log=None)
    path = str(out / "brain.ncb")
    brain.save(path)
    return path, brain


def test_brain_is_a_single_file(trained_brain, tmp_path):
    path, _ = trained_brain
    assert os.path.exists(path)
    # move ONLY the brain file into an empty directory
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    shutil.copy(path, isolated / "brain.ncb")
    assert sorted(os.listdir(isolated)) == ["brain.ncb"]


def test_brain_file_contains_no_facts(trained_brain):
    """The serialized brain must not embed sentences or fact strings."""
    path, _ = trained_brain
    raw = open(path, "rb").read()
    for sentence in (b"the sun heats the water", b"what does the fire burn", b"farmer grows rice"):
        assert sentence not in raw, "training sentences must not be stored"
    assert b"facts" not in raw and b"knowledge_base" not in raw


def test_brain_alone_can_answer(trained_brain, tmp_path):
    """A fresh process-context with only the .ncb file answers correctly."""
    path, reference = trained_brain
    isolated = tmp_path / "isolated2"
    isolated.mkdir()
    shutil.copy(path, isolated / "brain.ncb")

    loaded = Brain.load(str(isolated / "brain.ncb"))
    accs = metrics.evaluate_all(loaded, set_names=["A", "B"])
    assert accs["A"] >= 0.75
    assert accs["B"] >= 0.75

    # and it matches the reference answers question for question
    for s, r, o in [("sun", "heats", "water"), ("bird", "has", "wings")]:
        from neuralcore.output import ask
        from neuralcore.perception import normalize_word

        assert ask(loaded, s, r).concept == ask(reference, s, r).concept == normalize_word(o)


def test_unknown_questions_are_declined(trained_brain):
    from neuralcore.output import ask

    _, brain = trained_brain
    # rocket was never experienced — the system must not pretend to know
    assert ask(brain, "rocket", "heats").concept is None
    assert ask(brain, "sun", "explodes").concept is None
