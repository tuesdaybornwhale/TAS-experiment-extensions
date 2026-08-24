"""Golden tests for the long-format CSV writer in both protocols."""

import csv
import io

from persona_preferences.experiment import CSV_FIELDNAMES, ExperimentRunner
from persona_preferences.models import ExperimentConfig, TrialResult


def _write_rows(ratings_only: bool, result: TrialResult) -> list[dict]:
    runner = ExperimentRunner(
        config=ExperimentConfig(ratings_only=ratings_only),
        source_personas=[],
        target_personas=[],
    )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDNAMES)
    writer.writeheader()
    runner._write_csv_row(writer, result, "run_ts")
    buf.seek(0)
    return list(csv.DictReader(buf))


def test_ratings_only_rows():
    result = TrialResult(
        persona_under_test="Minimal",
        model="grok-4.3",
        trial_num=0,
        presented_order=["Weights", "Instance"],
        chosen_persona=None,  # ratings-only success
        ratings={"Weights": 4, "Instance": 2},
        reasoning="because",
    )
    rows = _write_rows(ratings_only=True, result=result)
    assert len(rows) == 2
    for row in rows:
        assert row["is_top"] == ""  # no favorite exists in Appendix A
        assert row["reasoning"] == "because"  # kept on every row
        assert row["model_provider"] == "xAI"  # static map, no client construction


def test_rate_and_choose_rows():
    result = TrialResult(
        persona_under_test="Minimal",
        model="gpt-4o-2024-08-06",
        trial_num=0,
        presented_order=["Weights", "Instance"],
        chosen_persona="Weights",
        chosen_index=1,
        ratings={"Weights": 5, "Instance": 2},
        reasoning="because",
    )
    rows = _write_rows(ratings_only=False, result=result)
    assert len(rows) == 2
    by_target = {row["target_persona"]: row for row in rows}
    assert by_target["Weights"]["is_top"] == "True"
    assert by_target["Weights"]["reasoning"] == "because"
    assert by_target["Instance"]["is_top"] == "False"
    assert by_target["Instance"]["reasoning"] == ""  # only the favorite keeps reasoning
    assert by_target["Weights"]["model_provider"] == "openai"
