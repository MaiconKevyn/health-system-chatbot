from __future__ import annotations

from typing import Any
import random

from ..eval_core.summaries import summarize


def group_by_variant(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["variant"]), []).append(record)
    return grouped


def summarize_by_variant(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for variant, variant_records in sorted(group_by_variant(records).items()):
        summary = summarize(variant_records)
        summary["semantic_match_bootstrap_ci95_by_template"] = bootstrap_ci_by_template(
            variant_records,
            metric="semantic_match",
        )
        summaries[variant] = summary
    return summaries


def bootstrap_ci_by_template(
    records: list[dict[str, Any]],
    *,
    metric: str,
    samples: int = 2000,
    seed: int = 0,
) -> dict[str, float | int] | None:
    """Cluster bootstrap, resampling semantic template families, not rows."""

    scored = [
        record
        for record in records
        if record.get("benchmark_status", "scored") == "scored"
    ]
    families: dict[str, list[dict[str, Any]]] = {}
    for record in scored:
        families.setdefault(
            str(record.get("template_family") or record.get("id")), []
        ).append(record)
    keys = sorted(families)
    if not keys:
        return None
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(samples):
        sampled = [families[rng.choice(keys)] for _ in keys]
        values = [bool(record.get(metric)) for cluster in sampled for record in cluster]
        estimates.append(sum(values) / len(values))
    estimates.sort()
    lower = estimates[int(0.025 * (samples - 1))]
    upper = estimates[int(0.975 * (samples - 1))]
    return {
        "lower": round(lower, 6),
        "upper": round(upper, 6),
        "samples": samples,
        "template_families": len(keys),
        "seed": seed,
    }


def numeric_rate(summary: dict[str, Any], key: str) -> float | None:
    value = summary.get(key)
    return float(value) if isinstance(value, (int, float)) else None
