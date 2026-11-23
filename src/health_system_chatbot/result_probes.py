from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from .models import QuestionContract
from .text import normalize_text


@dataclass(frozen=True)
class ResultProbeReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)


def _row_values(
    columns: list[str], rows: Iterable[dict[str, Any] | tuple[Any, ...] | list[Any]]
) -> list[list[Any]]:
    materialized: list[list[Any]] = []
    for row in rows:
        if isinstance(row, dict):
            materialized.append([row.get(column) for column in columns])
        else:
            materialized.append(list(row))
    return materialized


def probe_result_contract(
    *,
    contract: QuestionContract | None,
    columns: list[str],
    rows: Iterable[dict[str, Any] | tuple[Any, ...] | list[Any]],
    truncated: bool = False,
) -> ResultProbeReport:
    """Check output invariants derived only from the question contract.

    These checks never compare against ground-truth values.  They are suitable
    for both production and evaluation paths.
    """

    if contract is None:
        return ResultProbeReport()
    values = _row_values(columns, rows)
    errors: list[str] = []
    warnings: list[str] = []
    findings: list[dict[str, Any]] = []

    threshold_percent = contract.cumulative_threshold_percent
    if threshold_percent is not None:
        cumulative_indexes = [
            index
            for index, column in enumerate(columns)
            if any(
                token in normalize_text(column)
                for token in ("acumul", "cumulative", "cobertura")
            )
        ]
        if not cumulative_indexes:
            errors.append(
                "Cumulative-threshold question returned no cumulative coverage column."
            )
            findings.append(
                {
                    "layer": "result_probe",
                    "code": "cumulative_column_missing",
                    "threshold_percent": threshold_percent,
                }
            )
        else:
            index = cumulative_indexes[0]
            numeric = [
                float(row[index])
                for row in values
                if index < len(row)
                and isinstance(row[index], (int, float, Decimal))
                and not isinstance(row[index], bool)
            ]
            scale = 1.0 if numeric and max(abs(value) for value in numeric) <= 1.000001 else 100.0
            threshold = threshold_percent / 100.0 * scale
            crossing = next(
                (position for position, value in enumerate(numeric) if value >= threshold),
                None,
            )
            findings.append(
                {
                    "layer": "result_probe",
                    "code": "cumulative_threshold",
                    "threshold": threshold,
                    "observed_last": numeric[-1] if numeric else None,
                    "crossing_index": crossing,
                    "row_count": len(values),
                }
            )
            if crossing is None:
                errors.append(
                    "Cumulative result does not include a row that reaches the requested threshold."
                )
            elif crossing != len(numeric) - 1:
                errors.append(
                    "Cumulative result includes rows after the first threshold-crossing row."
                )
            if truncated:
                warnings.append(
                    "Cumulative result was truncated; threshold coverage may be incomplete."
                )

    return ResultProbeReport(errors=errors, warnings=warnings, findings=findings)
