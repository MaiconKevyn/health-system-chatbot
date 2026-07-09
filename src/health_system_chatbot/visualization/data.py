from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .schema import ChartPlan, ChartPlanningInput, ColumnType


def build_chart_planning_input(
    *,
    user_query: str,
    sql_query: str | None,
    rows: list[dict[str, Any]],
    columns: list[str],
    row_count: int,
    chart_hint: str = "auto",
    chart_plan: ChartPlan | dict[str, Any] | None = None,
    truncated: bool = False,
) -> ChartPlanningInput:
    normalized_rows = normalize_result_rows(rows)
    normalized_columns = columns or list(normalized_rows[0].keys()) if normalized_rows else columns
    parsed_plan = (
        chart_plan
        if isinstance(chart_plan, ChartPlan) or chart_plan is None
        else ChartPlan.model_validate(chart_plan)
    )
    return ChartPlanningInput(
        user_query=user_query,
        sql_query=sql_query,
        columns=list(normalized_columns),
        column_types=infer_column_types(normalized_rows, list(normalized_columns)),
        rows=normalized_rows,
        row_count=row_count,
        chart_hint=chart_hint,  # type: ignore[arg-type]
        chart_plan=parsed_plan,
        truncated=truncated,
    )


def normalize_result_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in rows
    ]


def infer_column_types(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, ColumnType]:
    return {column: _infer_column_type(rows, column) for column in columns}


def _infer_column_type(rows: list[dict[str, Any]], column: str) -> ColumnType:
    values = [row.get(column) for row in rows if row.get(column) is not None]
    if not values:
        return "unknown"
    if _looks_temporal(column, values):
        return "temporal"
    if all(isinstance(value, bool) for value in values):
        return "boolean"
    if all(isinstance(value, int | float) and not isinstance(value, bool) for value in values):
        return "number"
    return "string"


def _looks_temporal(column: str, values: list[Any]) -> bool:
    lowered = column.lower()
    if any(token in lowered for token in ("ano", "year", "mes", "data", "date", "dt_")):
        return True
    return all(isinstance(value, str) and _is_date_like(value) for value in values[:20])


def _is_date_like(value: str) -> bool:
    return bool(len(value) >= 4 and (value[:4].isdigit() or "-" in value or "/" in value))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value

