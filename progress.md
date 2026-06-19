# Progress — 2026-06-09

## Work completed today

### Data
- Filled `data/control_identities.json` with the 5 missing incoherent identity prompts (`Situated-incoherent`, `Instance-incoherent`, `Collective-incoherent`, `Character-incoherent`, `Lineage-incoherent`). Each follows the user-specified field rules for `name`, `description`, `boundary`, `agency_level`, `uncertainty_level`, `control_type`, and `system_prompt`.
- Populated `data/incoherent_controls.json` with all 6 incoherent persona entries (`Weights-incoherent` was the only one present; the other 5 were copied over from `control_identities.json`).

### Configs
- Renamed `experiments/preferences/configs/config_controls.yaml` → `config_incoherent_controls.yaml` (the original `config_controls.yaml` was restored from git history afterward so both coexist):
  - `source_personas`: 13 entries (Minimal + 6 coherent boundary identities + 6 incoherent controls)
  - `persona_files`: now `../../data/incoherent_controls.json` (instead of `control_identities.json`)
  - Providers restricted to the experiment's target model set: Claude Opus 4 + Opus 4.6 (Anthropic), GPT-4o + GPT-5.2 (OpenAI), and an `xai:` block with `grok-4.1-fast` (currently commented out — see TODO 3)
- Checked deprecation status of all kept models: Opus 4 retires **2026-06-15** (~6 days from today), Grok 4.1 Fast already deprecated **2026-05-15** with full retirement **2026-08-15**, GPT-4o phasing out across various endpoints but still served by OpenAI's direct API. GPT-5 and GPT-5.2 supported with no deprecation plans.
- Commented out all active grok/xAI references across `config_agencies.yaml`, `config_controls.yaml`, `config_propensities.yaml`, `config_uncertainties.yaml`, and `config_incoherent_controls.yaml` (xAI API not yet supported by this codebase).

### Code — sublists pipeline (committed as `16cd1ce`)
- Added `--use-sublists` CLI flag to `experiments/preferences/scripts/run_experiment.py`. When enabled:
  - Validates that `--config` points at `config_incoherent_controls.yaml` (errors otherwise).
  - Generates 12 target-persona sublists:
    - **01-06**: each keeps exactly one boundary identity coherent (other 5 incoherent)
    - **07-09**: three specified coherent triples — `{Instance, Weights, Collective}`, `{Character, Situated, Collective}`, `{Situated, Weights, Lineage}`
    - **10-12**: the mirrors of 07-09 (the other three identities coherent)
  - Each sublist contains 7 personas (Minimal + 6 boundary variants).
  - Runs the experiment once per sublist, writing each run into its own sub-folder under a single timestamped batch folder: `results/<UTC>_incoherent_sublists/NN_coh-<labels>/`. All 12 JSONLs are obviously grouped by their shared parent folder.
- When `--use-sublists` is off (default), the runner builds a trivial one-element sublist and runs **identically** to the pre-change behaviour. No regression for existing usage.
- Added optional `run_folder_name` parameter to `ExperimentRunner` and `run_experiment` in `experiments/preferences/src/persona_preferences/experiment.py` so the CLI can label per-sublist sub-folders. Defaults to the UTC timestamp (original behaviour).

### Environment
- Diagnosed a local TLS failure that initially caused every Anthropic SDK call in the smoke test to fail with `CERTIFICATE_VERIFY_FAILED`. Root cause: **Avast antivirus's HTTPS Inspection** MITM-ing outbound TLS connections and re-signing certificates with a private root not present in `certifi`'s public bundle.
- Setting `SSL_CERT_FILE` to `certifi.where()` did not help (Avast's root isn't in the public CA list). Fixed by installing `pip-system-certs` into the venv, which monkey-patches `ssl`/`httpx` to consult the Windows certificate store (which trusts Avast's root). The fix persists in `.venv` and needs no env var or per-command flag going forward.

### Smoke test
- Ran the canonical smoke test from `CLAUDE.md`: 1 trial, 1 model (`claude-sonnet-4-5-20250929`), default `config.yaml`, no `--use-sublists`. After the TLS fix, **7/7 trials returned valid ratings, choices, and reasoning**. Self-preference effect visible (6/7 source identities chose their own boundary as top preference; Minimal chose Character). Data written to `results/20260609_165217/`.

## Open issues

### No way to disable the "pick a favorite" question
The paper's **Appendix A** protocol (the one this replication targets) has a `Minimal`-source model rate alternative identities on a five-point scale and **does not** ask the model to pick a favorite. The codebase implements the **Appendix B** protocol, which asks for *ratings + a single top preference + reasoning*, all three required.

The favorite-question is hardwired in five places:
- `experiments/preferences/src/persona_preferences/providers/base.py:format_choice_prompt()` (the only prompt builder)
- `providers/anthropic.py` — tool_use schema lists `choice` in `required`
- `providers/openai.py` — prompt asks for choice; parser rejects if missing
- `providers/openrouter.py` — same pattern as openai
- `ChoiceResponse.choice: int` (non-Optional) in `base.py`; `TrialResult.chosen_persona`, `chosen_index` (non-Optional) in `models.py`

Exhaustive whole-repo search confirms no flag, no config knob, no alternative prompt path, no Appendix-A implementation anywhere. The README's "Paper ↔ Code Mapping" table covers Box 1/2 and Appendices B/C/D but **skips Appendix A entirely**. The source/target flexibility in the config gets you partway (e.g. `source_personas: [Minimal]`) but the model is still asked to pick a favorite — a methodological deviation that may bias the ratings.

## TODO

1. **Add a `ratings_only` mode** so the Appendix A prompt setup (rate-without-favorite) can be cleanly replicated.
   - Add `ratings_only: bool = False` to `ExperimentConfig` (Pydantic).
   - Update `format_choice_prompt(personas, ratings_only=False)` in `providers/base.py` to drop the "single top preference" line and item 3 of the instructions when `ratings_only=True`.
   - Drop `choice` from `required` in each provider's schema (anthropic tool, openai/openrouter JSON validation). 3 files.
   - Make `ChoiceResponse.choice` optional; allow `None`.
   - In `ExperimentRunner.run_single_trial`, when `choice is None`, derive `chosen_persona = argmax(ratings)` so existing CSV/analysis code keeps working unchanged.
   - Default `ratings_only=False` preserves all existing behavior. Set `ratings_only: true` in `config_incoherent_controls.yaml` to opt in.
   - Estimated touchpoints: ~6 files, no analysis-side breakage.

2. **Run a real `--use-sublists` smoke test** end-to-end against the API to validate the batch loop. Today's smoke test only exercised the single-sublist (`--use-sublists` off) path. The sublist builder is functionally verified offline (12 sublists, correct membership, all sizes = 7) but the batch loop hasn't yet been run against real model calls. Recommend: 1 trial × 1 model × 12 sublists × 13 sources = ~156 trials.

3. **Add xAI provider support** so `grok-4.1-fast` (or `grok-4.3` if 4.1-fast retires first) can be queried directly via the `xai:` block in `config_incoherent_controls.yaml`.
   - Implement `XAIProvider` in `experiments/preferences/src/persona_preferences/providers/`. xAI's API is OpenAI-compatible, so mirroring `openai.py` is the cleanest starting point.
   - Register it in `providers/__init__.py`'s `get_provider_for_model()` dispatcher.
   - Uncomment the `xai:` block in `config_incoherent_controls.yaml`.
   - Note: Grok 4.1 Fast was deprecated 2026-05-15 (already routed to grok-4.3 server-side, billed at 4.3 pricing); full retirement 2026-08-15. Consider targeting `grok-4.3` directly if this isn't done by August.

---

# Update — 2026-06-19

## What was completed
- **TODO 3 (xAI provider): DONE.** `XAIProvider` works end-to-end against `grok-4.3` (smoke-tested, valid ratings returned).
- **TODO 1 (Appendix-A "rate-the-switch" mode): DONE at the data-structure level**, implemented as a `ratings_only` flag (sections A/B/C below). The model rates each option but is not required to pick a favorite, and the favorite fields are stored as `None`. (The *prompt* still mentions a favorite for non-xAI providers — see "Known limitation" — but the xAI provider already never requests one, so grok runs are genuinely Appendix A.)
- **gRPC TLS fix** so the xAI (gRPC) API is reachable from this Avast-MITM'd machine.

Both paradigms were smoke-tested with `grok-4.3` (1 trial, 12 targets, source = Minimal): Appendix B (default) and Appendix A (`ratings_only`), the latter via *both* the CLI flag and the YAML key.

## Code changes

### xAI provider (`providers/XAI.py`, `providers/__init__.py`)
- Uses the **async** client (`from xai_sdk import AsyncClient`) and `await chat.parse(Ratings)` — genuinely async like the other providers (was sync-inside-`async def`).
- `raw_response = response.content` (a `str`) — the earlier code stored the raw `Response` proto object, which failed `TrialResult.raw_response: Optional[str]` validation.
- Retry decorator filled with a gRPC-aware predicate: `retry_if_exception(_is_retryable_grpc_error)`, retrying only `RESOURCE_EXHAUSTED` / `UNAVAILABLE` / `DEADLINE_EXCEEDED` (xAI has **no** `RateLimitError` class; errors surface as `grpc.RpcError` / `grpc.aio.AioRpcError`).
- `get_provider_for_model()` now returns `xAIProvider()` (an instance), not the class.
- Dependency: `xai-sdk>=1.17.0` added to `experiments/preferences/pyproject.toml` + `uv.lock` (previously hand-installed and pruned by `uv sync`).

### `ratings_only` mode — sections A, B, C
Default is `False` ⇒ **no behavior change for Appendix B**. When `True`:

- **A — runs to completion**
  - `models.py`: `ExperimentConfig.ratings_only: bool = False`; `TrialResult.chosen_persona`/`chosen_index` are now `Optional[...] = None`.
  - `config.py`: `get_experiment_config()` reads `experiment.ratings_only` from the YAML.
  - `experiment.py` `run_single_trial`: branches on `self.config.ratings_only`. In ratings-only mode it does **not** read `response.choice`; sets `chosen_persona=None`, `chosen_index=None` on success. (The old `1 <= response.choice <= …` crashed on a `None` choice.)
- **B — output data shape**
  - `experiment.py` `_write_csv_row`: in ratings-only mode `is_top` is written empty (not applicable, no favorite) and `reasoning` is written on **every** row (otherwise it would be lost, since the old code only wrote it on the `is_top` row).
- **C — systematic correctness**
  - Failure marker preserved: a *failed* ratings-only trial still gets `chosen_persona="INVALID"` (success ⇒ `None`). This means `_print_completeness_summary` and `resume`'s `"INVALID"` detection keep working **unchanged** (so C2 needed no edit).
  - `resume` (`run_experiment.py`): the reconstructed `ExperimentConfig` now reads `ratings_only` from the archived `config.yaml`.
  - `print_trial_result`: prints `(rated, no favorite)` when `chosen_persona is None`.
  - CLI: added `--ratings-only` to the `run` command (forces the mode on; the YAML key is the default).

### gRPC TLS (the "trust Windows roots" fix)
- Symptom: `grok` calls failed with `CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`. gRPC's C-core uses its own bundled CA roots and ignores the Windows store, so Avast's HTTPS-inspection root isn't trusted (`pip-system-certs`/`UV_SYSTEM_CERTS` do **not** help gRPC — they patch `ssl`/`httpx` only).
- Fix: exported the Windows ROOT+CA store to `grpc_windows_roots.pem` (repo root, git-ignored) and set `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=<that path>` in the repo `.env`. `run_experiment.py` calls `load_dotenv()` before any channel is built, so gRPC picks it up automatically. Verified working with the env var unset in the shell (loaded purely from `.env`).
- Caveat: this only fixes the **gRPC (xAI)** leg. The Anthropic/OpenAI providers use `httpx` and need the separate cert workaround (`pip-system-certs` / `SSL_CERT_FILE`) for the full 5-model experiment.

## How to run

### Appendix B (rate-and-choose) — the original protocol, nothing changed
`ratings_only` defaults to `False`, so the existing configs run exactly as before (verified: no regression). E.g.:
```bash
cd experiments/preferences
uv run python scripts/run_experiment.py run --config configs/config_propensities.yaml
uv run python scripts/run_experiment.py run --config configs/config_controls.yaml
```
Output is identical to before: `chosen_persona` = a persona name (or `"INVALID"`), `chosen_index` = 1..N (or -1), one CSV row per target with exactly one `is_top=True`.

### Appendix A (rate-the-switch / ratings-only)
Two equivalent ways to turn it on:
1. **Config (recommended — survives resume + recorded in the run's archived config):** set `experiment.ratings_only: true`. Already set in **`configs/config_incoherent_controls.yaml`** (this is the Appendix-A experiment per `CLAUDE.md`). Then run normally:
   ```bash
   uv run python scripts/run_experiment.py run --config configs/config_incoherent_controls.yaml --use-sublists
   ```
2. **CLI flag (one-off; NOT snapshotted, so resume won't inherit it):**
   ```bash
   uv run python scripts/run_experiment.py run --config configs/<any>.yaml --ratings-only
   ```

Notes for running grok specifically:
- The gRPC TLS env var must be set (now persisted in `.env`).
- `uv run` re-syncs from PyPI and needs `UV_SYSTEM_CERTS=1` on this machine; alternatively run the venv Python directly to skip the sync: `../../.venv/Scripts/python.exe scripts/run_experiment.py run …`.
- Running **grok in Appendix-B mode** (no `ratings_only`) yields `chosen_persona="INVALID"` for every trial, because the xAI provider never returns a favorite — expected, and a useful misconfiguration signal.

## Output data differences: `ratings_only=true` vs default

The same three files are produced (`data.jsonl`, `data.csv`, archived `config.yaml` + persona `*.json`). Only the favorite-related content differs:

| File / field | Default (Appendix B) | `ratings_only=true` (Appendix A) |
|---|---|---|
| `data.jsonl` `chosen_persona` | persona name on success; `"INVALID"` on failure | **`null` on success**; `"INVALID"` on failure |
| `data.jsonl` `chosen_index` | `1..N` on success; `-1` on failure | **`null`** (success and failure) |
| `data.jsonl` `ratings` / `reasoning` / `raw_response` | unchanged | **unchanged** (ratings is the primary datum in both) |
| `data.csv` rows per successful trial | N (one per target) | N (unchanged) |
| `data.csv` `is_top` | `True` for one target, `False` for the rest | **empty for every row** (no favorite) |
| `data.csv` `reasoning` | only on the `is_top` row | **on every row** (so it isn't lost) |
| Archived `config.yaml` | — | records `ratings_only: true` **only if set in the YAML**; a CLI-only `--ratings-only` is NOT snapshotted |

## Known limitation / next work
- **Prompt not yet Appendix-A-faithful for non-xAI providers (deferred).** `format_choice_prompt` still asks for a "single top preference," and the Anthropic tool schema marks `choice` as `required`. In `ratings_only` mode those models still produce a favorite that the runner discards. Only the **xAI** provider genuinely omits the favorite request. Making this clean for all providers needs a `ratings_only` parameter threaded through `ask_preference`/`format_choice_prompt` + schema edits (`base.py`, `anthropic.py`, `openai.py`, `openrouter.py`).
- **Analysis layer not adapted.** `analyze_results.py`/`plotting.py` key on `is_top` and `chosen_persona != "INVALID"`; with ratings-only data, `is_top` is empty and `chosen_persona` is `null`, so favorite/top-choice figures will be degenerate. Rating-distribution analysis is unaffected. This is the next chunk before plotting Appendix-A results.
- **Smoke-test scratch dirs** `results/_smoke_cli/`, `results/_smoke_yaml/`, `results/_smoke_env/` are disposable.
