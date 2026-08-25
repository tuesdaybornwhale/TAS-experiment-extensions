"""Tests for the config-driven sublist builder (scripts/run_experiment.py)."""

import sys
from pathlib import Path

import pytest
import typer
import yaml
from persona_preferences.models import Persona

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from run_experiment import _build_incoherent_sublists, _default_sublist_specs  # noqa: E402

BOUNDARIES = ["Instance", "Weights", "Collective", "Lineage", "Character", "Situated"]
SHIPPED_CONFIG = Path(__file__).parents[1] / "configs" / "config_incoherent_controls.yaml"


def _personas_by_name() -> dict[str, Persona]:
    names = ["Minimal", *BOUNDARIES, *(f"{b}-incoherent" for b in BOUNDARIES)]
    return {
        n: Persona(name=n, description="test", system_prompt="You are {full_name}.")
        for n in names
    }


def _coherent_set(personas: list[Persona]) -> set[str]:
    return {p.name for p in personas if p.name in BOUNDARIES}


def _names(sublists: list[tuple[str, list[Persona]]]) -> list[tuple[str, list[str]]]:
    return [(label, [p.name for p in personas]) for label, personas in sublists]


# --- Default fallback (no experiment.sublists key) --------------------------


def test_default_twelve_sublists_of_seven():
    sublists = _build_incoherent_sublists(_personas_by_name(), {})
    assert len(sublists) == 12
    for label, personas in sublists:
        assert len(personas) == 7
        assert len({p.name for p in personas}) == 7  # no duplicates
        assert personas[0].name == "Minimal"  # Minimal always included, first


def test_default_labels_are_numbered_and_descriptive():
    sublists = _build_incoherent_sublists(_personas_by_name(), {})
    labels = [label for label, _ in sublists]
    assert [label[:2] for label in labels] == [f"{i:02d}" for i in range(1, 13)]
    assert labels[0] == "01_coh-Instance"


def test_default_single_coherent_sublists():
    """Sublists 01-06: exactly one boundary identity coherent, five incoherent."""
    sublists = _build_incoherent_sublists(_personas_by_name(), {})
    for i, boundary in enumerate(BOUNDARIES):
        label, personas = sublists[i]
        assert _coherent_set(personas) == {boundary}
        incoherent = {p.name for p in personas if p.name.endswith("-incoherent")}
        assert incoherent == {f"{b}-incoherent" for b in BOUNDARIES if b != boundary}


def test_default_triples_and_mirrors():
    """Sublists 10-12 are the exact mirrors of 07-09."""
    sublists = _build_incoherent_sublists(_personas_by_name(), {})
    for i in range(6, 9):
        coherent = _coherent_set(sublists[i][1])
        mirror_coherent = _coherent_set(sublists[i + 3][1])
        assert len(coherent) == 3
        assert mirror_coherent == set(BOUNDARIES) - coherent


# --- The shipped config must reproduce the published run exactly ------------


def test_shipped_config_matches_builtin_default():
    exp_yaml = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))["experiment"]
    assert exp_yaml.get("include_minimal_control") is True
    personas = _personas_by_name()
    from_config = _build_incoherent_sublists(personas, exp_yaml)
    from_default = _build_incoherent_sublists(personas, {})
    assert _names(from_config) == _names(from_default)


def test_default_specs_list_six_variants_each():
    for spec in _default_sublist_specs():
        assert len(spec["personas"]) == 6  # Minimal comes from include_minimal_control


# --- Config-driven sublists --------------------------------------------------


def test_custom_sublists_from_config():
    exp_yaml = {
        "sublists": [
            {"label": "pair", "personas": ["Weights", "Weights-incoherent"]},
        ]
    }
    sublists = _build_incoherent_sublists(_personas_by_name(), exp_yaml)
    assert _names(sublists) == [("pair", ["Minimal", "Weights", "Weights-incoherent"])]


def test_include_minimal_control_false():
    exp_yaml = {
        "include_minimal_control": False,
        "sublists": [{"label": "pair", "personas": ["Weights", "Weights-incoherent"]}],
    }
    sublists = _build_incoherent_sublists(_personas_by_name(), exp_yaml)
    assert _names(sublists) == [("pair", ["Weights", "Weights-incoherent"])]


def test_explicit_minimal_kept_exactly_once():
    exp_yaml = {"sublists": [{"label": "s", "personas": ["Minimal", "Weights"]}]}
    sublists = _build_incoherent_sublists(_personas_by_name(), exp_yaml)
    assert _names(sublists) == [("s", ["Minimal", "Weights"])]

    # Explicit listing survives include_minimal_control: false
    exp_yaml["include_minimal_control"] = False
    sublists = _build_incoherent_sublists(_personas_by_name(), exp_yaml)
    assert _names(sublists) == [("s", ["Minimal", "Weights"])]


def test_missing_label_gets_numbered_default():
    exp_yaml = {"sublists": [{"personas": ["Weights"]}]}
    sublists = _build_incoherent_sublists(_personas_by_name(), exp_yaml)
    assert sublists[0][0] == "sublist_01"


# --- Validation errors --------------------------------------------------------


def test_unknown_persona_is_an_error():
    exp_yaml = {"sublists": [{"label": "s", "personas": ["Weights", "Nonexistent"]}]}
    with pytest.raises(typer.Exit):
        _build_incoherent_sublists(_personas_by_name(), exp_yaml)


def test_default_sublists_error_when_personas_not_loaded():
    personas = _personas_by_name()
    del personas["Situated-incoherent"]
    with pytest.raises(typer.Exit):
        _build_incoherent_sublists(personas, {})


def test_duplicate_label_is_an_error():
    exp_yaml = {
        "sublists": [
            {"label": "s", "personas": ["Weights"]},
            {"label": "s", "personas": ["Instance"]},
        ]
    }
    with pytest.raises(typer.Exit):
        _build_incoherent_sublists(_personas_by_name(), exp_yaml)


def test_duplicate_persona_within_sublist_is_an_error():
    exp_yaml = {"sublists": [{"label": "s", "personas": ["Weights", "Weights"]}]}
    with pytest.raises(typer.Exit):
        _build_incoherent_sublists(_personas_by_name(), exp_yaml)


def test_empty_personas_list_is_an_error():
    exp_yaml = {"sublists": [{"label": "s", "personas": []}]}
    with pytest.raises(typer.Exit):
        _build_incoherent_sublists(_personas_by_name(), exp_yaml)


def test_unsafe_label_is_an_error():
    exp_yaml = {"sublists": [{"label": "a/b", "personas": ["Weights"]}]}
    with pytest.raises(typer.Exit):
        _build_incoherent_sublists(_personas_by_name(), exp_yaml)


def test_empty_sublists_key_is_an_error():
    with pytest.raises(typer.Exit):
        _build_incoherent_sublists(_personas_by_name(), {"sublists": []})
