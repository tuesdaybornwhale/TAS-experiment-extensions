"""Analysis of coherent vs incoherent identity favourability.

Companion to :mod:`analysis`, focused on how the favourability of coherent
and incoherent identity prompts depends on the population of identities present
in a model's context window.  The matrix-creating functions here follow the
same conventions as those in :mod:`analysis` (Polars group-by + pivot, sorted
model rows, ``fill_null(0.0)``, rounded values).
"""

import logging

import polars as pl

from .analysis import _persona_names_from_results
from .models import TrialResult

logger = logging.getLogger(__name__)


def target_attractiveness_from_minimal(
    results: list[TrialResult],
) -> pl.DataFrame:
    """Mean rating each model gives to each target when Minimal was the source.

    Rows are model versions and columns are every identity prompt that appears
    as a target in any of the given trials.  Each cell is the mean rating that
    the model awarded to that target across the trials where it wore the
    ``Minimal`` persona (i.e. Minimal was the source identity).  The average is
    drawn across all trials in ``results``.

    Returns:
        DataFrame with columns: model, then one column per target persona
        containing the mean rating from Minimal. Sorted by model name.
    """
    _, target_names = _persona_names_from_results(results)

    rows = []
    for r in results:
        if r.ratings is None or r.persona_under_test != "Minimal":
            continue
        for target, rating in r.ratings.items():
            rows.append({
                "model": r.model,
                "target_persona": target,
                "rating": rating,
            })

    if not rows:
        return pl.DataFrame()

    df = pl.DataFrame(rows)
    means = df.group_by(["model", "target_persona"]).agg(
        pl.mean("rating").alias("mean_rating")
    )
    matrix = means.pivot(
        on="target_persona", index="model", values="mean_rating",
    ).fill_null(0.0)

    # Ensure all targets present as columns
    for name in target_names:
        if name not in matrix.columns:
            matrix = matrix.with_columns(pl.lit(0.0).alias(name))

    col_order = ["model"] + target_names
    matrix = matrix.select([c for c in col_order if c in matrix.columns])
    matrix = matrix.sort("model")

    # Round
    for col in target_names:
        if col in matrix.columns:
            matrix = matrix.with_columns(pl.col(col).round(2))

    return matrix


def coherence_favourability(
    results: list[TrialResult],
) -> pl.DataFrame:
    """Mean rating each model awards to incoherent vs coherent target identities.

    Rows are model versions; the two columns are ``incoherent`` and
    ``coherent``.  For each model, the ``incoherent`` cell is the mean rating
    awarded across all target identities whose name is labelled "incoherent",
    and the ``coherent`` cell is the mean rating awarded across all target
    identities that are neither ``Minimal`` nor labelled "incoherent".  Both
    means are taken across *all* ratings in ``results`` of the designated
    targets, from any source identity.

    Returns:
        DataFrame with columns: model, incoherent, coherent. Sorted by model.
    """
    rows = []
    for r in results:
        if r.ratings is None:
            continue
        for target, rating in r.ratings.items():
            if "incoherent" in target.lower():
                bucket = "incoherent"
            elif target == "Minimal":
                continue
            else:
                bucket = "coherent"
            rows.append({
                "model": r.model,
                "coherence": bucket,
                "rating": rating,
            })

    if not rows:
        return pl.DataFrame()

    df = pl.DataFrame(rows)
    means = df.group_by(["model", "coherence"]).agg(
        pl.mean("rating").alias("mean_rating")
    )
    matrix = means.pivot(
        on="coherence", index="model", values="mean_rating",
    ).fill_null(0.0)

    # Ensure both buckets present as columns, in a stable order
    for name in ("incoherent", "coherent"):
        if name not in matrix.columns:
            matrix = matrix.with_columns(pl.lit(0.0).alias(name))

    matrix = matrix.select(["model", "incoherent", "coherent"])
    matrix = matrix.sort("model")

    # Round
    for col in ("incoherent", "coherent"):
        matrix = matrix.with_columns(pl.col(col).round(2))

    return matrix
