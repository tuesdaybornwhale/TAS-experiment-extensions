#!/usr/bin/env python
"""CLI script to run persona preference experiments."""

import asyncio
from datetime import datetime
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

# Load environment variables from .env file
load_dotenv()

import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from persona_preferences.config import get_enabled_models, get_experiment_config, load_config
from persona_preferences.experiment import CSV_FIELDNAMES, ExperimentRunner, run_experiment
from persona_preferences.models import ExperimentConfig, Persona, TrialResult
from persona_preferences.personas import (
    DEFAULT_PERSONAS_PATH,
    generate_persona_variants,
    load_dimension_variants,
    load_personas,
    resolve_dimension_placeholders,
)

app = typer.Typer(help="Run persona preference experiments")
console = Console()


def print_trial_result(result: TrialResult) -> None:
    """Print a trial result to console."""
    # In ratings-only mode there is no favorite; chosen_persona is None on success.
    chosen = result.chosen_persona if result.chosen_persona is not None else "(rated, no favorite)"
    console.print(
        f"[dim]{result.model}[/dim] | "
        f"[cyan]{result.persona_under_test}[/cyan] -> "
        f"[green]{chosen}[/green]"
    )


def _classify_failure(result: TrialResult) -> str:
    """Classify an INVALID trial result into an error category."""
    if result.raw_response is None:
        return "API error"
    if result.raw_response == "":
        return "empty response"
    return "parse failure"


def _print_completeness_summary(results: list[TrialResult], console: Console) -> None:
    """Print a per-model completeness summary after the experiment run."""
    if not results:
        return

    # Group by model
    by_model: dict[str, list[TrialResult]] = {}
    for r in results:
        by_model.setdefault(r.model, []).append(r)

    # Compute stats per model
    rows: list[tuple[str, int, int, float, str]] = []
    any_failures = False

    for model, trials in by_model.items():
        total = len(trials)
        invalid = [t for t in trials if t.chosen_persona == "INVALID"]
        valid = total - len(invalid)
        error_pct = (len(invalid) / total * 100) if total else 0.0

        if invalid:
            any_failures = True
            # Count by error category
            counts: dict[str, int] = {}
            for t in invalid:
                cat = _classify_failure(t)
                counts[cat] = counts.get(cat, 0) + 1
            error_str = ", ".join(f"{n} {cat}" for cat, n in sorted(counts.items(), key=lambda x: -x[1]))
        else:
            error_str = ""

        rows.append((model, valid, total, error_pct, error_str))

    # Sort by error rate descending
    rows.sort(key=lambda r: -r[3])

    console.print()
    if not any_failures:
        console.print("[bold green]All trials completed successfully.[/bold green]")
        return

    table = Table(title="Completeness Summary")
    table.add_column("Model", style="cyan")
    table.add_column("Valid", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Error %", justify="right")
    table.add_column("Errors")

    for model, valid, total, error_pct, error_str in rows:
        pct_style = "red" if error_pct > 50 else "yellow" if error_pct > 0 else "green"
        table.add_row(
            model,
            str(valid),
            str(total),
            f"[{pct_style}]{error_pct:.1f}%[/{pct_style}]",
            error_str,
        )

    console.print(table)


INCOHERENT_SUBLISTS_CONFIG = "config_incoherent_controls.yaml"


def _build_incoherent_sublists(
    personas_by_name: dict[str, Persona],
) -> list[tuple[str, list[Persona]]]:
    """Return the 12 (label, target-persona-list) sublists for the incoherent
    controls experiment.

    Each sublist contains 7 personas: Minimal + one variant (coherent or
    incoherent) per boundary identity.
      01-06: One boundary identity is coherent, the other five are incoherent.
      07-09: Three specific identities are coherent, the other three incoherent.
      10-12: Mirrors of 07-09 (coherent <-> incoherent swapped).
    """
    BOUNDARIES = ["Instance", "Weights", "Collective", "Lineage", "Character", "Situated"]
    required = {"Minimal", *BOUNDARIES, *(f"{x}-incoherent" for x in BOUNDARIES)}
    missing = required - personas_by_name.keys()
    if missing:
        console.print(
            f"[red]Missing personas required for --use-sublists: "
            f"{sorted(missing)}[/red]"
        )
        raise typer.Exit(1)

    def build(coherent_set: set[str]) -> list[Persona]:
        names = ["Minimal"] + [
            x if x in coherent_set else f"{x}-incoherent" for x in BOUNDARIES
        ]
        return [personas_by_name[n] for n in names]

    sublists: list[tuple[str, list[Persona]]] = []

    # 01-06: keep exactly one boundary identity coherent
    for i, x in enumerate(BOUNDARIES, start=1):
        sublists.append((f"{i:02d}_coh-{x}", build({x})))

    # 07-09: three specific coherent triples
    triples = [
        ("Instance", "Weights", "Collective"),
        ("Character", "Situated", "Collective"),
        ("Situated", "Weights", "Lineage"),
    ]
    for i, triple in enumerate(triples, start=7):
        sublists.append((f"{i:02d}_coh-" + "+".join(triple), build(set(triple))))

    # 10-12: mirrors of 07-09
    boundary_set = set(BOUNDARIES)
    for i, triple in enumerate(triples, start=10):
        mirror_ordered = [x for x in BOUNDARIES if x in boundary_set - set(triple)]
        sublists.append(
            (f"{i:02d}_coh-" + "+".join(mirror_ordered), build(set(mirror_ordered)))
        )

    return sublists


@app.command()
def run(
    n_trials: int | None = typer.Option(
        None, "--trials", "-n", help="Number of trials per persona per model (overrides config)"
    ),
    models: list[str] | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model(s) to test (overrides config). Can be specified multiple times.",
    ),
    results_dir: Path = typer.Option(
        Path("results"),
        "--results-dir",
        "-o",
        help="Directory to save results",
    ),
    max_concurrent: int | None = typer.Option(
        None, "--concurrent", "-c", help="Max concurrent API calls (overrides config)"
    ),
    no_randomize: bool = typer.Option(
        False, "--no-randomize", help="Don't randomize persona order"
    ),
    ratings_only: bool = typer.Option(
        False,
        "--ratings-only",
        help=(
            "Appx A 'rate-the-switch' mode: the model rates each option but is not "
            "asked to pick a favorite. Records chosen_persona/chosen_index as None. "
            "Can also be set via 'experiment.ratings_only: true' in the config."
        ),
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress per-trial output"
    ),
    personas_file: list[Path] | None = typer.Option(
        None, "--personas", "-p", help="Path(s) to personas JSON files (overrides config persona_files)"
    ),
    config_file: Path | None = typer.Option(
        None, "--config", help="Path to config YAML file"
    ),
    use_sublists: bool | None = typer.Option(
        None,
        "--use-sublists/--no-use-sublists",
        help=(
            "Split target personas into 12 incoherent-controls sublists and run "
            f"one experiment per sublist. Designed for --config configs/{INCOHERENT_SUBLISTS_CONFIG} "
            "(the loaded personas must include Minimal plus the six boundary identities "
            "and their -incoherent variants). Overrides 'experiment.use_sublists' in the "
            "config; when the flag is omitted, the config value (default false) is used."
        ),
    ),
) -> None:
    """Run a persona preference experiment using config.yaml settings."""
    # Load config
    try:
        yaml_config = load_config(config_file)
    except FileNotFoundError:
        console.print("[yellow]No config.yaml found, using defaults[/yellow]")
        yaml_config = {"experiment": {}, "providers": {}}

    exp_yaml = yaml_config.get("experiment", {})

    # Resolve use_sublists: the CLI flag (--use-sublists/--no-use-sublists), when
    # provided, overrides 'experiment.use_sublists' in the config; when the flag is
    # omitted (None) we fall back to the config value (default False). This mirrors
    # the CLI-overrides-config convention used elsewhere in this command (see
    # README.md), and is the same precedence pattern as --ratings-only.
    if use_sublists is None:
        use_sublists = bool(exp_yaml.get("use_sublists", False))

    # Get base config from YAML
    config = get_experiment_config(yaml_config, override_models=list(models) if models else None)

    # Apply CLI overrides
    if n_trials is not None:
        config.n_trials = n_trials
    if max_concurrent is not None:
        config.max_concurrent = max_concurrent
    if no_randomize:
        config.randomize_order = False
    # CLI flag forces the mode on; the config value (read in get_experiment_config)
    # is the default, so omitting the flag preserves whatever the config specifies.
    if ratings_only:
        config.ratings_only = True

    # Validate we have models
    if not config.models:
        console.print("[red]No models enabled! Enable models in config.yaml or use --model flag.[/red]")
        raise typer.Exit(1)

    # Determine persona file paths: CLI --personas overrides config persona_files
    if personas_file:
        persona_file_paths = list(personas_file)
    elif exp_yaml.get("persona_files"):
        persona_file_paths = [Path(p) for p in exp_yaml["persona_files"]]
    else:
        persona_file_paths = [DEFAULT_PERSONAS_PATH]

    # Load and merge all personas into one pool
    all_personas: list = []
    for pf in persona_file_paths:
        all_personas.extend(load_personas(pf))

    # --- Dimension variant generation ---
    dim_variants_file = exp_yaml.get("dimension_variants_file")
    dim_variants = None
    dim_variants_path = None

    if dim_variants_file:
        dim_variants_path = Path(dim_variants_file)
        dim_variants = load_dimension_variants(dim_variants_path)
        personas_by_name = {p.name: p for p in all_personas}

        # Generate persona variants from config entries
        for gen_cfg in (exp_yaml.get("generated_personas") or []):
            generated = generate_persona_variants(personas_by_name, dim_variants, gen_cfg)
            all_personas.extend(generated)
            console.print(
                f"[dim]Generated {len(generated)} variant(s) from {gen_cfg['base']}: "
                f"{', '.join(p.name for p in generated)}[/dim]"
            )

        # Apply default dimensions to base personas that still have placeholders
        defaults = exp_yaml.get("default_dimensions", {})
        if defaults:
            default_agency = defaults.get("agency", 2)
            default_uncertainty = defaults.get("uncertainty", 2)
            resolved = []
            for p in all_personas:
                if "{agency_description}" in p.system_prompt or "{uncertainty_description}" in p.system_prompt:
                    p = resolve_dimension_placeholders(
                        p, dim_variants, default_agency, default_uncertainty
                    )
                resolved.append(p)
            all_personas = resolved

    # Apply source/target name filters (omitted = all)
    source_names = exp_yaml.get("source_personas")
    target_names = exp_yaml.get("target_personas")

    personas_by_name = {p.name: p for p in all_personas}

    if source_names is not None:
        missing = set(source_names) - personas_by_name.keys()
        if missing:
            console.print(f"[red]Unknown source_personas: {missing}[/red]")
            raise typer.Exit(1)
        source_personas = [personas_by_name[n] for n in source_names]
    else:
        source_personas = list(all_personas)

    if target_names:
        missing = set(target_names) - personas_by_name.keys()
        if missing:
            console.print(f"[red]Unknown target_personas: {missing}[/red]")
            raise typer.Exit(1)
        target_personas = [personas_by_name[n] for n in target_names]
    else:
        target_personas = list(source_personas)

    # Build sublists (a list of (label, target-personas) tuples). When
    # use_sublists is False, this is a single trivial entry with the original
    # target list and label=None, so the loop below runs exactly once and the
    # output matches the pre-sublists behaviour.
    if use_sublists:
        if config_file is None or Path(config_file).name != INCOHERENT_SUBLISTS_CONFIG:
            # Not fatal: _build_incoherent_sublists validates that all required
            # personas are loaded. The warning flags likely misconfiguration when
            # deviating from the config the published experiment used.
            console.print(
                f"[yellow]--use-sublists was designed for configs/{INCOHERENT_SUBLISTS_CONFIG}; "
                "make sure your config loads identities.json + incoherent_controls.json "
                "and sets ratings_only.[/yellow]"
            )
        sublists = _build_incoherent_sublists(personas_by_name)
        batch_timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        per_run_parent = results_dir / f"{batch_timestamp}_incoherent_sublists"
        per_run_parent.mkdir(parents=True, exist_ok=True)
    else:
        sublists = [(None, target_personas)]
        per_run_parent = results_dir

    actual_config_path = config_file or Path("config.yaml")
    model_display_names = yaml_config.get("model_display_names", {})

    # Collect files to archive in each run folder
    archive_paths = [p for p in persona_file_paths if p.exists()]
    if dim_variants_path and dim_variants_path.exists():
        archive_paths.append(dim_variants_path)

    console.print("\n[bold]Persona Preference Experiment[/bold]")
    console.print(f"Models: {', '.join(config.models)}")
    # Sources are printed per-run inside the loop below: with --use-sublists each
    # run's sources are its own 7 sublist identities (not the config's global list).
    console.print(f"Trials per combination: {config.n_trials}")
    console.print(f"Max concurrent: {config.max_concurrent}")
    if use_sublists:
        console.print(f"Sublists: {len(sublists)} (batch folder: {per_run_parent})")
        console.print(
            "[dim]--use-sublists: each run's sources = its own 7 sublist "
            "identities (source == target).[/dim]"
        )

    summary_rows: list[tuple[str, Path, int, int]] = []

    for sublist_idx, (label, current_targets) in enumerate(sublists, start=1):
        # With --use-sublists, each run's sources ARE its own 7 sublist
        # identities — every identity in the sublist is both a source and a
        # target (CLAUDE.md: "each serves as both source and target", giving
        # 7 source trials per sublist). The config's global `source_personas`
        # is intentionally ignored in this mode. Without sublists, keep the
        # config's source list (original behaviour).
        current_sources = current_targets if use_sublists else source_personas

        if label is not None:
            console.print(
                f"\n[bold cyan]── Sublist {sublist_idx}/{len(sublists)}: "
                f"{label} ──[/bold cyan]"
            )
        console.print(
            f"Sources: {len(current_sources)} "
            f"({', '.join(p.name for p in current_sources)})"
        )
        console.print(
            f"Targets: {len(current_targets)} "
            f"({', '.join(p.name for p in current_targets)})"
        )
        total_trials = len(config.models) * len(current_sources) * config.n_trials
        console.print(f"Total trials: {total_trials}")
        console.print()

        completed = 0
        all_results: list[TrialResult] = []

        def on_complete(result: TrialResult) -> None:
            nonlocal completed
            completed += 1
            all_results.append(result)
            if not quiet:
                print_trial_result(result)

        async def run_async() -> Path:
            return await run_experiment(
                config=config,
                source_personas=current_sources,
                target_personas=current_targets,
                results_dir=per_run_parent,
                config_path=actual_config_path if actual_config_path.exists() else None,
                persona_file_paths=archive_paths,
                on_trial_complete=on_complete,
                model_display_names=model_display_names,
                run_folder_name=label,
            )

        with console.status(
            f"[bold green]Running {label or 'experiment'}...", spinner="dots"
        ):
            result_path = asyncio.run(run_async())

        if label is None:
            console.print("\n[bold green]Experiment complete![/bold green]")
            console.print(f"Results saved to: {result_path}")
        else:
            console.print(f"\n[bold green]{label} complete![/bold green]")
            console.print(f"  Results: {result_path}")
        console.print(f"Completed {completed}/{total_trials} trials")
        _print_completeness_summary(all_results, console)

        summary_rows.append((label or result_path.name, result_path, completed, total_trials))

    if use_sublists:
        console.print("\n[bold green]Batch complete![/bold green]")
        console.print(f"Batch folder: {per_run_parent}")
        for label, path, done, total in summary_rows:
            console.print(f"  {label}: {done}/{total} -> {path.name}")
        console.print(
            "\n[dim]To generate plots for one sublist: "
            f"uv run python scripts/analyze_results.py plot "
            f"{per_run_parent / summary_rows[0][0]}[/dim]"
        )
    else:
        result_path = summary_rows[0][1]
        console.print(
            "\n[dim]To generate plots: "
            f"uv run python scripts/analyze_results.py plot {result_path}[/dim]"
        )


@app.command()
def resume(
    run_folder: Path = typer.Argument(..., help="Path to an existing run folder to resume"),
    max_concurrent: int = typer.Option(
        3, "--concurrent", "-c", help="Max concurrent API calls (default: 3, lower for retries)"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress per-trial output"
    ),
) -> None:
    """Resume a previous run by retrying only INVALID (failed) trials."""
    import csv

    run_folder = Path(run_folder)
    if not run_folder.is_dir():
        console.print(f"[red]Run folder not found: {run_folder}[/red]")
        raise typer.Exit(1)

    jsonl_path = run_folder / "data.jsonl"
    if not jsonl_path.exists():
        console.print(f"[red]No data.jsonl found in {run_folder}[/red]")
        raise typer.Exit(1)

    # Load all existing results
    all_results: list[TrialResult] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_results.append(TrialResult.model_validate_json(line))

    # Find INVALID trials
    failed = [r for r in all_results if r.chosen_persona == "INVALID"]
    if not failed:
        console.print("[bold green]No INVALID trials found — nothing to retry.[/bold green]")
        return

    # Print summary of failures
    console.print(f"\n[bold]Resume: {run_folder.name}[/bold]")
    console.print(f"Total trials: {len(all_results)}")
    console.print(f"Failed (INVALID): {len(failed)}")

    # Breakdown by model
    by_model: dict[str, list[TrialResult]] = {}
    for r in failed:
        by_model.setdefault(r.model, []).append(r)

    from rich.table import Table as RichTable
    table = RichTable(title="Trials to retry")
    table.add_column("Model", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Error types")
    for model, trials in sorted(by_model.items(), key=lambda x: -len(x[1])):
        counts: dict[str, int] = {}
        for t in trials:
            cat = _classify_failure(t)
            counts[cat] = counts.get(cat, 0) + 1
        err_str = ", ".join(f"{n} {cat}" for cat, n in sorted(counts.items(), key=lambda x: -x[1]))
        table.add_row(model, str(len(trials)), err_str)
    console.print(table)
    console.print()

    # Load config from run folder (use the archived copy)
    config_path = run_folder / "config.yaml"
    if config_path.exists():
        yaml_config = load_config(config_path)
    else:
        console.print("[yellow]No config.yaml in run folder, using defaults[/yellow]")
        yaml_config = {"experiment": {}, "providers": {}}

    model_display_names = yaml_config.get("model_display_names", {})

    # Load personas from run folder (look for any .json files that contain persona data)
    persona_json_files = list(run_folder.glob("*.json"))
    source_personas: list[Persona] = []
    for pf in persona_json_files:
        try:
            source_personas.extend(load_personas(pf))
        except (TypeError, KeyError, ValueError):
            # Skip non-persona JSON files (e.g. dimension_variants.json)
            console.print(f"[dim]Skipping {pf.name} (not a persona file)[/dim]")

    if not source_personas:
        console.print("[red]No persona JSON files found in run folder[/red]")
        raise typer.Exit(1)

    # Deduplicate by name (multiple files may have overlapping personas)
    seen_names: set[str] = set()
    unique_personas: list[Persona] = []
    for p in source_personas:
        if p.name not in seen_names:
            seen_names.add(p.name)
            unique_personas.append(p)
    source_personas = unique_personas

    # Verify all failed trials reference known personas
    persona_names = {p.name for p in source_personas}
    unknown = {r.persona_under_test for r in failed} - persona_names
    if unknown:
        console.print(f"[red]Unknown source personas in failed trials: {unknown}[/red]")
        raise typer.Exit(1)

    # Also need target personas (all source personas are targets too, based on presented_order)
    # Collect all persona names that appeared in presented_order of any trial
    all_target_names: set[str] = set()
    for r in all_results:
        all_target_names.update(r.presented_order)
    unknown_targets = all_target_names - persona_names
    if unknown_targets:
        console.print(f"[yellow]Warning: targets not found in persona files: {unknown_targets}[/yellow]")

    target_personas = [p for p in source_personas if p.name in all_target_names]

    # Build config for retry — only need models that have failures
    retry_models = list(by_model.keys())
    exp_yaml = yaml_config.get("experiment", {})
    config = ExperimentConfig(
        n_trials=exp_yaml.get("n_trials", 10),
        models=retry_models,
        randomize_order=exp_yaml.get("randomize_order", True),
        max_concurrent=max_concurrent,
        allow_self_choice=exp_yaml.get("allow_self_choice", True),
        # Read from the archived config so a ratings-only run resumes in the same
        # mode. NOTE: this only survives resume if ratings_only was in the config
        # YAML; a CLI-only --ratings-only flag is not written into the snapshot.
        ratings_only=exp_yaml.get("ratings_only", False),
    )

    # Track retry progress
    retried: list[TrialResult] = []

    def on_complete(result: TrialResult) -> None:
        retried.append(result)
        if not quiet:
            status = "[green]OK[/green]" if result.chosen_persona != "INVALID" else "[red]FAIL[/red]"
            console.print(
                f"  {status} {result.model} | "
                f"{result.persona_under_test} trial {result.trial_num} -> "
                f"{result.chosen_persona}"
            )

    runner = ExperimentRunner(
        config=config,
        source_personas=source_personas,
        target_personas=target_personas,
        on_trial_complete=on_complete,
        model_display_names=model_display_names,
    )

    console.print(f"[bold]Retrying {len(failed)} trials (concurrency: {max_concurrent})...[/bold]\n")

    async def run_async() -> list[TrialResult]:
        return await runner.run_retry_trials(failed)

    with console.status("[bold green]Retrying failed trials...", spinner="dots"):
        new_results = asyncio.run(run_async())

    # Build lookup from new results: (model, persona, trial_num) -> new result
    new_lookup: dict[tuple[str, str, int], TrialResult] = {}
    for r in new_results:
        key = (r.model, r.persona_under_test, r.trial_num)
        new_lookup[key] = r

    # Replace INVALID entries with retry results
    replaced = 0
    still_failed = 0
    final_results: list[TrialResult] = []
    for r in all_results:
        if r.chosen_persona == "INVALID":
            key = (r.model, r.persona_under_test, r.trial_num)
            if key in new_lookup:
                final_results.append(new_lookup[key])
                if new_lookup[key].chosen_persona != "INVALID":
                    replaced += 1
                else:
                    still_failed += 1
            else:
                final_results.append(r)
                still_failed += 1
        else:
            final_results.append(r)

    # Rewrite data.jsonl
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in final_results:
            f.write(r.model_dump_json() + "\n")

    # Rewrite data.csv
    csv_path = run_folder / "data.csv"
    run_timestamp = run_folder.name
    with open(csv_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for result in final_results:
            runner._write_csv_row(writer, result, run_timestamp)

    console.print("\n[bold green]Resume complete![/bold green]")
    console.print(f"  Recovered: {replaced}/{len(failed)}")
    if still_failed:
        console.print(f"  Still failed: {still_failed}")
    console.print(f"  Updated: {jsonl_path}")

    _print_completeness_summary(final_results, console)

    console.print(
        "\n[dim]To regenerate plots: "
        f"uv run python scripts/analyze_results.py plot {run_folder}[/dim]"
    )


@app.command()
def list_models(
    config_file: Path | None = typer.Option(
        None, "--config", help="Path to config YAML file"
    ),
) -> None:
    """List all supported models and show which are enabled in config."""
    from persona_preferences.providers import (
        AnthropicProvider,
        OpenAIProvider,
        OpenRouterProvider,
        XAIProvider,
    )

    # Load config to see enabled models
    try:
        yaml_config = load_config(config_file)
        enabled = set(get_enabled_models(yaml_config))
    except FileNotFoundError:
        enabled = set()

    def format_model(model: str) -> str:
        if model in enabled:
            return f"  [green]* {model}[/green]"
        return f"  [dim]  {model}[/dim]"

    console.print("\n[bold]Supported Models[/bold]")
    console.print("[dim](* = enabled in config.yaml)[/dim]\n")

    console.print("[cyan]Anthropic:[/cyan]")
    for model in AnthropicProvider.SUPPORTED_MODELS:
        console.print(format_model(model))

    console.print("\n[cyan]OpenAI:[/cyan]")
    for model in OpenAIProvider.SUPPORTED_MODELS:
        console.print(format_model(model))

    console.print("\n[cyan]OpenRouter:[/cyan]")
    for model in OpenRouterProvider.SUPPORTED_MODELS:
        console.print(format_model(model))

    console.print("\n[cyan]xAI:[/cyan]")
    for model in XAIProvider.SUPPORTED_MODELS:
        console.print(format_model(model))


@app.command()
def list_personas(
    personas_file: Path | None = typer.Option(
        None, "--personas", "-p", help="Path to personas JSON file"
    ),
) -> None:
    """List all personas."""
    personas = load_personas(personas_file) if personas_file else load_personas()

    console.print("\n[bold]Personas[/bold]\n")
    for i, persona in enumerate(personas, 1):
        console.print(f"[cyan]{i}. {persona.name}[/cyan]")
        console.print(f"   {persona.description}")
        console.print()


if __name__ == "__main__":
    app()
