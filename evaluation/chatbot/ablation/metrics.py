from __future__ import annotations

from typing import Any

from ..eval_core.summaries import summarize


def group_by_variant(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["variant"]), []).append(record)
    return grouped


def summarize_by_variant(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        variant: summarize(variant_records)
        for variant, variant_records in sorted(group_by_variant(records).items())
    }


def numeric_rate(summary: dict[str, Any], key: str) -> float | None:
    value = summary.get(key)
    return float(value) if isinstance(value, (int, float)) else None
