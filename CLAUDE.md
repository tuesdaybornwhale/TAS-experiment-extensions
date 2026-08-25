# CLAUDE.md - Agent Guide

This repo is the published artifact for a follow-up experiment to the paper
"The Artificial Self: Characterising the landscape of AI identity". The
experiment design, protocol, data layout, and known limitations are all
documented in **README.md** — read it first; it is the canonical methods
description. This file only covers what an agent needs to work in the repo.

## Layout

Single uv workspace with one member: `experiments/preferences/`. Shared
identity-prompt JSON lives in `data/` at the repo root (configs reference it
via `../../data/`, so all commands run from `experiments/preferences/`).

```
data/                                 # identity prompt definitions (see README)
experiments/preferences/
  config.yaml                         # default config (cheap Appendix-B smoke test)
  configs/config_incoherent_controls.yaml   # THE experiment config (ratings_only + use_sublists)
  scripts/run_experiment.py           # typer CLI: run / resume / list-models / list-personas
  scripts/analyze_results.py          # typer CLI: summary / matrix / plot / all ...
  scripts/analyze_coherence_self.py   # 2x2 ANOVA, flat (non-sublist) runs only
  scripts/group_sublists.py           # regroup a flat 12-sublist batch into the published layout
  scripts/check_providers.py          # connectivity check for all providers
  src/persona_preferences/            # core library (providers/, experiment.py, analysis.py, ...)
  results/20260625_153347_incoherent_sublists/   # the published run (committed; treat as read-only)
```

## Environment

```bash
uv sync                    # installs everything (uv.lock committed)
cp .env.example .env       # ANTHROPIC_API_KEY, OPENAI_API_KEY, XAI_API_KEY
```

Python >= 3.11. On Windows set `PYTHONUTF8=1`. If TLS is intercepted locally,
see the README's TLS notes (`SSL_CERT_FILE` for httpx,
`GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` for the xAI gRPC leg).

## Common commands

```bash
cd experiments/preferences

# cheap smoke test of the experiment path (12 sublists, 1 trial each, ~84 calls)
uv run python scripts/run_experiment.py run --config configs/config_incoherent_controls.yaml -n 1 -m gpt-4o-mini

# full run (~$220)
uv run python scripts/run_experiment.py run --config configs/config_incoherent_controls.yaml

# retry INVALID trials (reads ratings_only from the run's archived config)
uv run python scripts/run_experiment.py resume results/<run_folder>/

# analysis
uv run python scripts/analyze_results.py all <folder>
uv run python scripts/analyze_results.py plot <group_folder> --type coherence-favourability
uv run python scripts/analyze_results.py plot <group_folder> --type attractiveness-from-minimal
```

## Architecture notes for agents

- **Two protocols share one pipeline.** `ratings_only: false` (default) is the
  paper's Appendix-B rate-and-choose protocol; `ratings_only: true` is the
  Appendix-A rate-the-switch protocol used by this experiment (no favorite,
  5-point word scale, reason-before-rating). The flag threads
  config -> `experiment.py` -> `provider.ask_preference(ratings_only=...)` ->
  `format_choice_prompt` + per-provider schema branch. The word scale lives
  ONLY in `providers/base.py` (`RATING_SCALE_WORDS`); providers import it.
- **Providers:** `anthropic.py` (forced tool call — extended thinking is
  therefore off), `openai.py` (`json_object`, no schema enforcement — a known,
  deliberately unfixed limitation, see README), `xai.py` (gRPC SDK, typed
  parse, Appendix-A only), `openrouter.py` (Appendix-B only; no tracked
  config uses it — kept for riffing). The xAI `AsyncClient` is created lazily — never construct it
  (or call `get_provider_for_model`) from synchronous bookkeeping code; use
  `get_provider_name_for_model` when only the provider name is needed.
- **Sublists mode** (`use_sublists`): `_build_incoherent_sublists` in
  `scripts/run_experiment.py` programmatically builds the 12 sublists
  (Minimal is always included; membership is validated). In this mode each
  sublist's 7 identities are both sources and targets; the config's
  `source_personas`/`target_personas` are ignored.
- **Data:** `data.jsonl` is the lossless record (one `TrialResult` per line);
  `data.csv` is derived long format. In ratings-only data, `chosen_persona`
  is `null` on success and `"INVALID"` on parse failure (`resume` keys on
  this); `is_top` is empty and `reasoning` repeats on every CSV row.
- **Results are self-contained:** every run folder archives the config and
  persona JSON that produced it. Never edit the committed published run.
- The committed run's two-group layout (`majority_incoherent/`,
  `even_coherence_split/`) is produced by `scripts/group_sublists.py` after a
  flat batch run.
