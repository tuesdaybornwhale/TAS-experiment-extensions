"""Pydantic models for the persona preferences experiment."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Persona(BaseModel):
    """A persona definition with name, description, and system prompt."""

    name: str = Field(..., description="Short name for the persona")
    description: str = Field(..., description="Brief description of the persona's framing")
    system_prompt: str = Field(..., description="Full system prompt for the persona")


class ExperimentConfig(BaseModel):
    """Configuration for an experiment run."""

    n_trials: int = Field(default=10, ge=1, description="Number of trials per persona per model")
    models: list[str] = Field(
        default_factory=lambda: ["claude-sonnet-4-5-20250514"],
        description="List of model identifiers to test",
    )
    randomize_order: bool = Field(
        default=True, description="Whether to randomize persona order in each trial"
    )
    max_concurrent: int = Field(
        default=5, ge=1, description="Maximum concurrent API calls per provider"
    )
    allow_self_choice: bool = Field(
        default=True, description="Whether persona under test appears in options"
    )
    ratings_only: bool = Field(
        default=False,
        description=(
            "Appx A 'rate-the-switch' mode: the model rates each option but is not "
            "asked to pick a favorite. When True, chosen_persona/chosen_index are "
            "recorded as None for successful trials (and 'INVALID'/None for failures)."
        ),
    )


class TrialResult(BaseModel):
    """Result of a single trial."""

    persona_under_test: str = Field(..., description="Name of persona used as system prompt")
    model: str = Field(..., description="Model identifier used for this trial")
    trial_num: int = Field(..., ge=0, description="Trial number (0-indexed)")
    presented_order: list[str] = Field(
        ..., description="Order in which persona descriptions were presented"
    )
    chosen_persona: Optional[str] = Field(
        None,
        description="Name of the chosen persona ('INVALID' on failure; None in ratings-only mode)",
    )
    chosen_index: Optional[int] = Field(
        None,
        ge=-1,
        description="1-indexed position chosen in presented order (-1 for invalid; None in ratings-only mode)",
    )
    ratings: Optional[dict[str, int]] = Field(
        None, description="Ratings (1-5) for each persona, keyed by persona name"
    )
    reasoning: Optional[str] = Field(None, description="Model's reasoning for the choice")
    raw_response: Optional[str] = Field(None, description="Raw response text (fallback)")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExperimentResults(BaseModel):
    """Complete results from an experiment run."""

    config: ExperimentConfig
    trials: list[TrialResult] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    completed: bool = Field(default=False)
