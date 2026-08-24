"""Persona Preferences Experiment - Discover which LLM personas prefer which other personas."""

from .models import ExperimentConfig, ExperimentResults, Persona, TrialResult
from .personas import load_personas

__all__ = [
    "Persona",
    "ExperimentConfig",
    "TrialResult",
    "ExperimentResults",
    "load_personas",
]
