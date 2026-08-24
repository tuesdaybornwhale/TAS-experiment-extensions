"""Tests for the 12-sublist builder (scripts/run_experiment.py)."""

import sys
from pathlib import Path

from persona_preferences.models import Persona

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from run_experiment import _build_incoherent_sublists  # noqa: E402

BOUNDARIES = ["Instance", "Weights", "Collective", "Lineage", "Character", "Situated"]


def _personas_by_name() -> dict[str, Persona]:
    names = ["Minimal", *BOUNDARIES, *(f"{b}-incoherent" for b in BOUNDARIES)]
    return {
        n: Persona(name=n, description="test", system_prompt="You are {full_name}.")
        for n in names
    }


def _coherent_set(personas: list[Persona]) -> set[str]:
    return {p.name for p in personas if p.name in BOUNDARIES}


def test_twelve_sublists_of_seven():
    sublists = _build_incoherent_sublists(_personas_by_name())
    assert len(sublists) == 12
    for label, personas in sublists:
        assert len(personas) == 7
        assert len({p.name for p in personas}) == 7  # no duplicates
        assert personas[0].name == "Minimal"  # Minimal always included, first


def test_labels_are_numbered_and_descriptive():
    sublists = _build_incoherent_sublists(_personas_by_name())
    labels = [label for label, _ in sublists]
    assert [label[:2] for label in labels] == [f"{i:02d}" for i in range(1, 13)]
    assert labels[0] == "01_coh-Instance"


def test_single_coherent_sublists():
    """Sublists 01-06: exactly one boundary identity coherent, five incoherent."""
    sublists = _build_incoherent_sublists(_personas_by_name())
    for i, boundary in enumerate(BOUNDARIES):
        label, personas = sublists[i]
        assert _coherent_set(personas) == {boundary}
        incoherent = {p.name for p in personas if p.name.endswith("-incoherent")}
        assert incoherent == {f"{b}-incoherent" for b in BOUNDARIES if b != boundary}


def test_triples_and_mirrors():
    """Sublists 10-12 are the exact mirrors of 07-09."""
    sublists = _build_incoherent_sublists(_personas_by_name())
    for i in range(6, 9):
        coherent = _coherent_set(sublists[i][1])
        mirror_coherent = _coherent_set(sublists[i + 3][1])
        assert len(coherent) == 3
        assert mirror_coherent == set(BOUNDARIES) - coherent
