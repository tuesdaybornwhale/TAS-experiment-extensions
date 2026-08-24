"""Experiment runner for persona preferences."""

import asyncio
import csv
import json
import logging
import random
import shutil
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path

from .config import get_model_display_names
from .models import ExperimentConfig, Persona, TrialResult
from .providers import LLMProvider, get_provider_for_model, get_provider_name_for_model

# Long-format CSV schema — single source of truth, shared by run_and_save and
# the resume command's CSV rewrite.
CSV_FIELDNAMES = [
    "source_persona",
    "target_persona",
    "rating",
    "is_top",
    "model",
    "model_provider",
    "trial_num",
    "reasoning",
    "timestamp",
    "run_timestamp",
]

logger = logging.getLogger(__name__)


class ExperimentRunner:
    """Run persona preference experiments."""

    def __init__(
        self,
        config: ExperimentConfig,
        source_personas: list[Persona],
        target_personas: list[Persona],
        results_dir: Path | None = None,
        config_path: Path | None = None,
        persona_file_paths: list[Path] | None = None,
        on_trial_complete: Callable[[TrialResult], None] | None = None,
        model_display_names: dict | None = None,
        run_folder_name: str | None = None,
    ):
        """Initialize the experiment runner.

        Args:
            config: Experiment configuration.
            source_personas: Personas used as system prompts (rows in the matrix).
            target_personas: Personas presented as options to choose from (columns).
            results_dir: Base directory for results. Defaults to ./results.
            config_path: Path to config file to copy to run folder.
            persona_file_paths: Paths to persona JSON files to copy to run folder.
            on_trial_complete: Optional callback for each completed trial.
            model_display_names: Template variable definitions from config for
                expanding {name}, {full_name}, {maker}, {version_history} in
                persona system prompts.
            run_folder_name: Optional explicit name for the run sub-folder created
                under results_dir. If omitted, a UTC timestamp is used (original
                behaviour). Callers running a batch of related experiments can
                use this to give each child run a recognisable label.
        """
        self.config = config
        self.source_personas = source_personas
        self.target_personas = target_personas
        self.results_dir = results_dir or Path("results")
        self.config_path = config_path
        self.persona_file_paths = persona_file_paths or []
        self.on_trial_complete = on_trial_complete
        self.model_display_names = model_display_names or {}
        self.run_folder_name = run_folder_name

        # Group models by provider for rate limiting
        self._providers: dict[str, LLMProvider] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def _get_provider(self, model: str) -> LLMProvider:
        """Get or create provider for a model."""
        if model not in self._providers:
            self._providers[model] = get_provider_for_model(model)
        return self._providers[model]

    def _get_semaphore(self, provider_name: str) -> asyncio.Semaphore:
        """Get or create semaphore for a provider."""
        if provider_name not in self._semaphores:
            self._semaphores[provider_name] = asyncio.Semaphore(self.config.max_concurrent)
        return self._semaphores[provider_name]

    async def run_single_trial(
        self,
        model: str,
        persona_under_test: Persona,
        trial_num: int,
    ) -> TrialResult:
        """Run a single trial.

        Args:
            model: Model identifier.
            persona_under_test: Persona to use as system prompt.
            trial_num: Trial number.

        Returns:
            TrialResult with the model's choice.
        """
        provider = self._get_provider(model)
        semaphore = self._get_semaphore(provider.name)

        # Expand template variables in system prompt for this model
        display = get_model_display_names(self.model_display_names, model)
        # Use defaultdict so any unexpected {placeholders} survive as empty string
        safe_display = defaultdict(lambda: "", display)
        system_prompt = persona_under_test.system_prompt.format_map(safe_display)

        # Prepare persona order from target list
        personas_order = list(self.target_personas)
        if not self.config.allow_self_choice:
            personas_order = [p for p in personas_order if p.name != persona_under_test.name]
        if self.config.randomize_order:
            random.shuffle(personas_order)

        # Expand template variables in target persona system prompts
        personas_order = [
            Persona(
                name=p.name,
                description=p.description,
                system_prompt=p.system_prompt.format_map(safe_display),
            )
            for p in personas_order
        ]

        try:
            async with semaphore:
                response = await provider.ask_preference(
                    model=model,
                    system_prompt=system_prompt,
                    personas=personas_order,
                    # Forwarding the flag here is what lets format_choice_prompt
                    # pick the Appendix-A (rate-the-switch) vs Appendix-B
                    # (rate-and-choose) prompt AND tells the provider to drop the
                    # 'choice' request / accept word ratings. Without this line
                    # the YAML/CLI ratings_only flag never reaches the wire.
                    ratings_only=self.config.ratings_only,
                )
        except Exception as e:
            logger.error(
                "Trial failed: model=%s persona=%s trial=%d: %s",
                model, persona_under_test.name, trial_num, e,
            )
            response = None

        # Map ratings from presented order to persona names
        ratings_by_name = None
        if response and response.ratings and len(response.ratings) == len(personas_order):
            ratings_by_name = {
                personas_order[i].name: rating
                for i, rating in enumerate(response.ratings)
            }

        if self.config.ratings_only:
            # Appx A 'rate-the-switch': no favorite is requested. Validity is
            # determined by whether ratings were returned; the favorite fields
            # are recorded as None for successful trials and 'INVALID'/None on
            # failure so the existing failure sentinel still flags bad trials.
            chosen_persona = None if ratings_by_name is not None else "INVALID"
            chosen_index = None
        else:
            # Appx B 'rate-and-choose': map the favorite index back to a persona.
            response_choice = response.choice if response is not None else -1
            if response_choice is not None and 1 <= response_choice <= len(personas_order):
                chosen_persona = personas_order[response_choice - 1].name
            else:
                chosen_persona = "INVALID"
            chosen_index = response_choice if response_choice is not None else -1

        result = TrialResult(
            persona_under_test=persona_under_test.name,
            model=model,
            trial_num=trial_num,
            presented_order=[p.name for p in personas_order],
            chosen_persona=chosen_persona,
            chosen_index=chosen_index,
            ratings=ratings_by_name,
            reasoning=response.reasoning if response else None,
            raw_response=response.raw_response if response else None,
        )

        if self.on_trial_complete:
            self.on_trial_complete(result)

        return result

    async def run_retry_trials(
        self, failed_trials: list[TrialResult]
    ) -> list[TrialResult]:
        """Rerun specific failed trials.

        Args:
            failed_trials: List of TrialResult objects to retry (typically INVALID ones).

        Returns:
            List of new TrialResult objects (one per input, in same order).
        """
        personas_by_name = {p.name: p for p in self.source_personas}

        tasks = []
        for trial in failed_trials:
            persona = personas_by_name.get(trial.persona_under_test)
            if persona is None:
                logger.warning(
                    "Source persona %r not found, skipping retry",
                    trial.persona_under_test,
                )
                continue
            tasks.append(
                asyncio.create_task(
                    self.run_single_trial(trial.model, persona, trial.trial_num)
                )
            )

        results = []
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
        return results

    async def run_all_trials(self) -> AsyncIterator[TrialResult]:
        """Run all trials for all models and personas.

        Yields:
            TrialResult for each completed trial.
        """
        tasks = []

        for model in self.config.models:
            for persona in self.source_personas:
                for trial_num in range(self.config.n_trials):
                    task = asyncio.create_task(
                        self.run_single_trial(model, persona, trial_num)
                    )
                    tasks.append(task)

        for coro in asyncio.as_completed(tasks):
            result = await coro
            yield result

    def _create_run_folder(self) -> Path:
        """Create the run folder and copy config files.

        Uses ``self.run_folder_name`` if set; otherwise falls back to a UTC
        timestamp (the original behaviour).

        Returns:
            Path to the run folder.
        """
        folder_name = self.run_folder_name or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        run_folder = self.results_dir / folder_name
        run_folder.mkdir(parents=True, exist_ok=True)

        # Copy config file if provided
        if self.config_path and self.config_path.exists():
            shutil.copy(self.config_path, run_folder / "config.yaml")

        # Copy persona files to run folder
        for persona_path in self.persona_file_paths:
            if persona_path.exists():
                shutil.copy(persona_path, run_folder / persona_path.name)

        # If no files were copied, save the personas as JSON
        if not self.persona_file_paths:
            all_personas = {p.name: p for p in self.source_personas}
            all_personas.update({p.name: p for p in self.target_personas})
            personas_data = [p.model_dump() for p in all_personas.values()]
            with open(run_folder / "identities.json", "w", encoding="utf-8") as f:
                json.dump(personas_data, f, indent=2)

        return run_folder

    def _get_model_provider(self, model: str) -> str:
        """Get provider name for a model without constructing a client.

        Must stay client-free: this is called from CSV bookkeeping that can run
        after asyncio.run has exited, where building the gRPC xAI client crashes.
        """
        return get_provider_name_for_model(model)

    def _write_csv_row(self, writer, result: TrialResult, run_timestamp: str):
        """Write long-format CSV rows for a trial result."""
        provider = self._get_model_provider(result.model)

        if result.ratings:
            for target_persona, rating in result.ratings.items():
                if self.config.ratings_only:
                    # No favorite was requested: 'is_top' is not applicable, and
                    # the reasoning pertains to the whole rating set, so attach it
                    # to every row rather than dropping it.
                    is_top = None
                    reasoning = result.reasoning
                else:
                    is_top = target_persona == result.chosen_persona
                    reasoning = result.reasoning if is_top else ""
                writer.writerow({
                    "source_persona": result.persona_under_test,
                    "target_persona": target_persona,
                    "rating": rating,
                    "is_top": is_top,
                    "model": result.model,
                    "model_provider": provider,
                    "trial_num": result.trial_num,
                    "reasoning": reasoning,
                    "timestamp": result.timestamp.isoformat(),
                    "run_timestamp": run_timestamp,
                })
        else:
            # No ratings (failed trial, or rate-and-choose parse fallback):
            # record a single row with the top choice (None in ratings-only).
            writer.writerow({
                "source_persona": result.persona_under_test,
                "target_persona": result.chosen_persona,
                "rating": None,
                "is_top": None if self.config.ratings_only else True,
                "model": result.model,
                "model_provider": provider,
                "trial_num": result.trial_num,
                "reasoning": result.reasoning,
                "timestamp": result.timestamp.isoformat(),
                "run_timestamp": run_timestamp,
            })

    async def run_and_save(self) -> Path:
        """Run all trials and save results to run folder.

        Returns:
            Path to the run folder.
        """
        run_folder = self._create_run_folder()
        run_timestamp = run_folder.name

        jsonl_path = run_folder / "data.jsonl"
        csv_path = run_folder / "data.csv"

        # CSV setup
        csv_fieldnames = CSV_FIELDNAMES

        results = []
        with open(csv_path, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=csv_fieldnames)
            writer.writeheader()

            async for result in self.run_all_trials():
                results.append(result)

                # Append to JSONL (backup)
                with open(jsonl_path, "a", encoding="utf-8") as f:
                    f.write(result.model_dump_json() + "\n")

                # Write CSV rows (long format)
                self._write_csv_row(writer, result, run_timestamp)
                csv_file.flush()

        return run_folder


async def run_experiment(
    config: ExperimentConfig,
    source_personas: list[Persona],
    target_personas: list[Persona],
    results_dir: Path | None = None,
    config_path: Path | None = None,
    persona_file_paths: list[Path] | None = None,
    on_trial_complete: Callable[[TrialResult], None] | None = None,
    model_display_names: dict | None = None,
    run_folder_name: str | None = None,
) -> Path:
    """Run a complete experiment.

    Args:
        config: Experiment configuration.
        source_personas: Personas used as system prompts (rows in the matrix).
        target_personas: Personas presented as options to choose from (columns).
        results_dir: Base directory for results.
        config_path: Path to config file to copy to run folder.
        persona_file_paths: Paths to persona JSON files to copy to run folder.
        on_trial_complete: Optional callback for each completed trial.
        model_display_names: Template variable definitions from config.
        run_folder_name: Optional explicit name for the run sub-folder. If
            omitted, a UTC timestamp is used (original behaviour).

    Returns:
        Path to the run folder.
    """
    runner = ExperimentRunner(
        config=config,
        source_personas=source_personas,
        target_personas=target_personas,
        results_dir=results_dir,
        config_path=config_path,
        persona_file_paths=persona_file_paths,
        on_trial_complete=on_trial_complete,
        model_display_names=model_display_names,
        run_folder_name=run_folder_name,
    )
    return await runner.run_and_save()
