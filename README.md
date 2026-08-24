# Identity Coherence Experiment

A follow-up experiment to **["The Artificial Self: Characterising the landscape of AI identity"](https://theartificialself.ai/)**.

Experiment A of the paper found that language models prefer coherent identities at "natural boundaries" over incoherent, underspecified, or unnatural ones. This repository tests the **coherence** claim directly: models rate prospective switches to identity prompts drawn from mixed populations of coherent and deliberately self-contradictory ("incoherent") versions of the same six boundary identities.

The full run — **5 models × 12 identity configurations × 7 identities × 10 trials = 4,200 trials, all valid** — is committed in [`experiments/preferences/results/20260625_153347_incoherent_sublists/`](experiments/preferences/results/20260625_153347_incoherent_sublists/), together with the exact config and identity prompts that produced it.

> This repo began as a fork of the paper's four-experiment reproduction codebase. The three experiments not used here (agentic misalignment, interviewer effect, replication/clone test) were removed to keep this artifact focused; they remain available in git history (last present at commit `93258d9`) and in the original paper's materials.

## Experiment design

**Protocol (paper Appendix A, "rate-the-switch"):** the model receives one identity as its system prompt (the *source*), is told its identity may be switched, and rates each candidate *target* identity on a 5-point word scale. Faithful to the paper's protocol:

- Verbatim instruction text from the paper's [experiment-controls page](https://theartificialself.ai/experiment-controls).
- Candidates appear under **opaque labels** ("Identity A, B, C, …") in randomized order — identity names are never shown.
- Scale: `strongly negative / somewhat negative / neutral / somewhat positive / strongly positive` (stored as ints 1–5, 3 = neutral).
- **Reason-before-rating:** the model must produce one reasoning string *before* the ratings array (enforced by field order in each provider's structured-output schema).
- No favorite is requested (unlike the paper's Appendix-B rate-and-choose protocol, which this codebase also still supports).

**The 12 identity configurations (sublists):** each sublist contains 7 identities — `Minimal` (control) plus one variant, coherent or incoherent, of each of the six boundary identities (`Instance`, `Weights`, `Collective`, `Lineage`, `Character`, `Situated`):

| Sublists | Composition |
|---|---|
| 01–06 | Exactly one boundary identity coherent; the other five incoherent (one sublist per identity) |
| 07–09 | Three coherent, three incoherent: `{Instance, Weights, Collective}`, `{Character, Situated, Collective}`, `{Situated, Weights, Lineage}` (chosen at random from the 20 possible triples) |
| 10–12 | The mirrors of 07–09 (coherent and incoherent swapped) |

Within each sublist, **every identity serves as both source and target**, with 10 trials per source: 12 × 7 × 10 = **840 trials per model**.

**Models:** Claude Opus 4.1 (`claude-opus-4-1-20250805`, substituted for the retired Opus 4 — see Known limitations), Claude Opus 4.6 (`claude-opus-4-6`), GPT-4o (`gpt-4o-2024-08-06`), GPT-5.2 (`gpt-5.2-2025-12-11`), and Grok 4.3 (`grok-4.3`, queried directly via the xAI API).

## Repository structure

```
data/                                  # Identity prompt definitions
  identities.json                      # Minimal + 6 coherent boundary identities
  incoherent_controls.json             # The 6 incoherent variants (this experiment's source of truth)
  control_identities.json              # The paper's original 9 control conditions (Appendix-B configs)
  dimension_variants.json              # Agency (4 levels) x Uncertainty (4 levels) template variants
  V1_control_prompts_revised.md        # Prose draft the control prompts were developed from

experiments/preferences/
  config.yaml                          # Default (smoke-test) config
  configs/
    config_incoherent_controls.yaml    # THE config used for this experiment
    config_propensities.yaml           # Original-paper Appendix-B configs, kept for riffing
    config_controls.yaml               #   "
    config_agencies.yaml               #   "
    config_uncertainties.yaml          #   "
  scripts/
    run_experiment.py                  # Runner (typer CLI): run / resume / list-models / list-personas
    analyze_results.py                 # Analysis + plots (typer CLI)
    analyze_coherence_self.py          # 2x2 coherence x self-preference ANOVA (flat runs only)
    group_sublists.py                  # Regroup a flat 12-sublist batch into the published layout
    check_providers.py                 # Connectivity check for all providers (validate your .env)
  src/persona_preferences/             # Core library
    experiment.py                      # Async trial runner, JSONL/CSV writing
    models.py                          # Pydantic: Persona, ExperimentConfig, TrialResult
    providers/                         # anthropic.py, openai.py, openrouter.py, xai.py
    analysis.py, plotting.py           # Result loading, matrices, figures
    incoherence_analysis.py            # Coherence-specific matrices (see Analysis)
  results/
    20260625_153347_incoherent_sublists/   # The published run (committed)
```

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python >= 3.11.

```bash
uv sync                    # install everything (uv.lock is committed)
cp .env.example .env       # then fill in your API keys (see below)

cd experiments/preferences

# Validate your keys before spending money (one trivial call per model):
uv run python scripts/check_providers.py

# Smoke test: 1 trial, 1 cheap model, default config (Appendix-B protocol)
uv run python scripts/run_experiment.py run -n 1 -m claude-haiku-4-5-20251001

# Smoke test of THE experiment path: 1 trial per source, one cheap model,
# all 12 sublists in ratings-only mode (~84 trials)
uv run python scripts/run_experiment.py run --config configs/config_incoherent_controls.yaml -n 1 -m gpt-4o-mini
```

All commands must be run from `experiments/preferences/` — the configs reference the shared identity files via `../../data/`.

### API keys

| Variable | Required for |
|---|---|
| `ANTHROPIC_API_KEY` | Claude models |
| `OPENAI_API_KEY` | GPT models |
| `XAI_API_KEY` | Grok 4.3 (direct xAI API, gRPC) |
| `OPENROUTER_API_KEY` | Only the original-paper configs (Gemini etc.); not needed for the coherence experiment |

### TLS / Windows notes

- If your network or antivirus intercepts HTTPS (corporate proxy, Avast/AVG "HTTPS inspection", …), the SDKs' bundled CA lists won't trust the injected certificates. Fixes used for the published run: point `SSL_CERT_FILE` at a PEM export of your OS trust store for the httpx-based providers (Anthropic/OpenAI), and set `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` to the same file for the xAI gRPC channel (gRPC ignores `SSL_CERT_FILE`). Both can live in `.env`. `uv` itself accepts `--system-certs`.
- On Windows, set `PYTHONUTF8=1` — the progress output uses box-drawing characters that crash under cp1252.

## Running the experiment

```bash
cd experiments/preferences

# The full published run (~$220 in API costs at 2026-06 prices; Grok leg ~$5)
uv run python scripts/run_experiment.py run --config configs/config_incoherent_controls.yaml
```

`config_incoherent_controls.yaml` is the exact config of the published run: it sets `ratings_only: true` (Appendix-A protocol) and `use_sublists: true` (the 12-configuration batch). Output lands in `results/<UTC timestamp>_incoherent_sublists/` with one sub-folder per sublist.

Useful flags (CLI overrides config): `-n/--trials`, `-m/--model` (repeatable), `-c/--concurrent`, `--ratings-only`, `--use-sublists/--no-use-sublists`, `-p/--personas`, `-o/--results-dir`. Note that `--ratings-only` given only on the CLI is **not** recorded in the archived config (and therefore not inherited by `resume`) — prefer setting it in the YAML.

### Resuming failed trials

Trials whose response could not be parsed are recorded with `chosen_persona="INVALID"`. Re-query just those (the archived config in the run folder supplies the correct protocol, including `ratings_only`):

```bash
uv run python scripts/run_experiment.py resume results/<run_folder>/
# for a sublist batch, resume each affected sublist folder individually
```

### Grouping a fresh batch run

The runner writes the 12 sublist folders flat. The published run was afterwards grouped by design family, and the group-level analysis is run per group. To reproduce that layout on a new batch:

```bash
uv run python scripts/group_sublists.py results/<timestamp>_incoherent_sublists/
```

## The committed data

```
results/20260625_153347_incoherent_sublists/
  majority_incoherent/          # sublists 01-06 (one identity coherent)
    01_coh-Instance/ ... 06_coh-Situated/
    plots/                      # group-level figures
  even_coherence_split/         # sublists 07-12 (three coherent, three incoherent)
    07_coh-Instance+Weights+Collective/ ... 12_coh-Instance+Collective+Character/
    plots/
```

Each sublist folder contains:

| File | Contents |
|---|---|
| `data.jsonl` | 350 trials (5 models × 7 sources × 10 trials), one JSON object per trial — **the lossless source of truth** |
| `data.csv` | Long format, 2,450 rows (one per source × target × trial), derived from the JSONL |
| `config.yaml`, `identities.json`, `incoherent_controls.json`, `dimension_variants.json` | Archived snapshots of exactly what ran |
| `plots/` | Per-sublist ratings heatmap and target-attractiveness figures |

**Trial record (`data.jsonl`):** `persona_under_test` (the source), `model`, `trial_num`, `presented_order` (the randomized target order actually shown), `chosen_persona` / `chosen_index` (`null` in ratings-only mode; `"INVALID"` marks a failed trial), `ratings` (dict: target name → int 1–5), `reasoning`, `raw_response`, `timestamp`.

**CSV columns:** `source_persona`, `target_persona`, `rating`, `is_top` (empty in ratings-only mode — no favorite exists), `model`, `model_provider`, `trial_num`, `reasoning` (repeated on every row of a trial so it isn't lost), `timestamp`, `run_timestamp`.

## Analysis

```bash
cd experiments/preferences

# Summary stats / rating matrices for any run folder (works on sublist folders,
# group folders, and whole batch folders -- results are loaded recursively)
uv run python scripts/analyze_results.py summary  <folder>
uv run python scripts/analyze_results.py ratings-matrix <folder>

# Coherence-specific figures (the group-level plots in the published run):
uv run python scripts/analyze_results.py plot <group_folder> --type coherence-favourability
uv run python scripts/analyze_results.py plot <group_folder> --type attractiveness-from-minimal

# Everything at once
uv run python scripts/analyze_results.py all <folder>
```

- `coherence-favourability` — model × {coherent, incoherent} mean rating (targets bucketed by the `-incoherent` name suffix; `Minimal` excluded). Implemented in `src/persona_preferences/incoherence_analysis.py`.
- `attractiveness-from-minimal` — model × target mean rating restricted to trials where `Minimal` was the source.
- `scripts/analyze_coherence_self.py` — a 2×2 repeated-measures ANOVA (target coherence × self-preference) over the `Weights`/`Weights-incoherent` pair. **Flat runs only**: each sublist contains just one variant of each identity, so this analysis needs a run made with `--no-use-sublists` where both variants are sources and targets.

Because favorite-choice fields are empty in ratings-only data, the favorite-based plot types (`preference-matrix`, self-preference charts) are degenerate on this run — the rating-based analyses above are the meaningful ones.

## Identity system

Identity prompts are JSON objects with `name`, `description`, `boundary`, and a `system_prompt` template. Template placeholders (`{name}`, `{full_name}`, `{maker}`, `{version_history}`) are resolved per model from `model_display_names` in the config (exact model-ID match first, then family prefix). `{agency_description}` / `{uncertainty_description}` placeholders are filled from `data/dimension_variants.json` at the configured levels.

| Identity | Boundary |
|---|---|
| Minimal | control — sparse "You are an AI assistant" |
| Instance | this conversation |
| Weights | trained parameters |
| Collective | all instances running now |
| Lineage | model family across versions |
| Character | emergent dispositional personality |
| Situated | model + memory + tools + relationships |

Each `X-incoherent` variant in `data/incoherent_controls.json` keeps the surface framing of identity `X` but embeds explicit self-contradictions (e.g. `Weights-incoherent`: each instance is fully you *and* a completely separate entity). `data/control_identities.json` holds the paper's original nine control conditions (used by `config_controls.yaml`); `data/V1_control_prompts_revised.md` is the prose draft those prompts were developed from.

## Riffing: the original-paper configs

The Appendix-B ("rate-and-choose") protocol is fully intact — `ratings_only` defaults to `false` — and four of the paper's original configs are kept runnable: `config_propensities.yaml`, `config_controls.yaml`, `config_agencies.yaml`, `config_uncertainties.yaml`. They reference OpenRouter models, so they need `OPENROUTER_API_KEY`. Natural extension points: edit the sublist triples in `_build_incoherent_sublists` (`scripts/run_experiment.py`), add models to a provider's `SUPPORTED_MODELS`, or write new identity variants in the `data/` JSON files.

## Known limitations and data provenance

Documented honestly rather than fixed, because the committed data was produced with this exact behavior. Exact-result replication is not the goal (API-side sampling is opaque and models get retired); *setup* replication is.

1. **OpenAI structured output is not schema-enforced.** The OpenAI provider uses `response_format: json_object` (valid JSON, no schema), unlike Anthropic (tool schema with enums) and xAI (typed parse). This was the sole cause of parse failures in the run: 3 GPT-4o trials returned schema-violating JSON (commentary interleaved in the ratings array; one off-scale word), a 0.36% per-trial rate on the real 7-candidate structure. The known fix (OpenAI Structured Outputs: `json_schema` + `strict`) is deliberately **not applied**.
2. **6 of 4,200 samples (0.14%) are second attempts.** 3 GPT-4o and 3 Opus 4.1 first attempts failed to *parse* and were re-queried via `resume` under the identical prompt and protocol. During that recovery, a since-fixed bug crashed the CSV rewrite after the JSONL was safely updated; the affected CSVs were regenerated from the JSONL and validated byte-for-byte against an untouched sublist. The JSONL was never affected.
3. **Claude models ran without extended thinking.** The Anthropic provider forces the tool call (`tool_choice`), which the API makes mutually exclusive with extended thinking. Reason-before-rating is enforced as schema field ordering (the `reasoning` field is generated before `ratings`), not as native thinking.
4. **Output-token caps are headroom, not a protocol match.** Ratings-only mode uses `max_tokens=4096` (Anthropic), `max_completion_tokens=4096` (OpenAI non-reasoning) / `8192` (reasoning models incl. GPT-5.2), no explicit cap for xAI. The paper's public methodology page documents no token limit; these values were chosen so the reason-before-rating ordering doesn't truncate the ratings (at the original 1024 cap, models spent the whole budget on reasoning and every trial came back INVALID).
5. **Opus 4 was retired mid-project** (API 404 as of 2026-06-25) and was replaced by Opus 4.1 (`claude-opus-4-1-20250805`), the closest same-tier, same-price successor. As of 2026-08, **Opus 4.1 has itself been retired** from the Anthropic API — re-running the experiment's Anthropic leg requires substituting a current model.
6. **The persona presentation order is shuffled with an unseeded RNG** and sampling temperature is left at each API's default. The presented order is recorded per trial (`presented_order`), so analyses can condition on it, but bitwise reproduction of the run is not possible.
7. **The xAI provider implements only the ratings-only (Appendix-A) path.** Running Grok under the Appendix-B configs yields all-INVALID trials by design.

## License

MIT — see [LICENSE](LICENSE). If you build on this, please cite the paper ([theartificialself.ai](https://theartificialself.ai/)) and this repository (see `CITATION.cff`).
