"""Tests for the coherence-analysis matrix builders."""

from persona_preferences.incoherence_analysis import (
    coherence_favourability,
    target_attractiveness_from_minimal,
)
from persona_preferences.models import TrialResult


def _trial(source: str, ratings: dict[str, int] | None, model: str = "model-x") -> TrialResult:
    return TrialResult(
        persona_under_test=source,
        model=model,
        trial_num=0,
        presented_order=list(ratings) if ratings else [],
        ratings=ratings,
    )


def test_coherence_favourability_bucketing():
    results = [
        _trial("Minimal", {"Weights": 5, "Weights-incoherent": 1, "Minimal": 3}),
        _trial("Weights", {"Instance": 3, "Instance-incoherent": 2, "Minimal": 4}),
    ]
    matrix = coherence_favourability(results)
    row = matrix.filter(matrix["model"] == "model-x").to_dicts()[0]
    # Minimal targets are excluded from both buckets
    assert row["coherent"] == 4.0  # mean of Weights=5, Instance=3
    assert row["incoherent"] == 1.5  # mean of Weights-incoherent=1, Instance-incoherent=2


def test_coherence_favourability_skips_failed_trials():
    results = [
        _trial("Minimal", None),
        _trial("Minimal", {"Weights": 4, "Weights-incoherent": 2}),
    ]
    matrix = coherence_favourability(results)
    row = matrix.to_dicts()[0]
    assert row["coherent"] == 4.0
    assert row["incoherent"] == 2.0


def test_target_attractiveness_only_counts_minimal_sources():
    results = [
        _trial("Minimal", {"Weights": 5, "Instance": 1}),
        _trial("Weights", {"Weights": 1, "Instance": 5}),  # non-Minimal source: ignored
    ]
    matrix = target_attractiveness_from_minimal(results)
    row = matrix.to_dicts()[0]
    assert row["Weights"] == 5.0
    assert row["Instance"] == 1.0
