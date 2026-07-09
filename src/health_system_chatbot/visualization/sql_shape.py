from __future__ import annotations

import re

import sqlglot
from sqlglot import expressions as exp

from .schema import ChartPlan, ChartSqlValidation


def validate_sql_against_chart_plan(chart_plan: ChartPlan | None, sql: str) -> ChartSqlValidation:
    if chart_plan is None or not chart_plan.requested:
        return ChartSqlValidation(is_valid=True)
    if not sql.strip():
        return ChartSqlValidation(is_valid=False, errors=["Chart SQL is empty."])

    output_names = _outer_select_output_names(sql)
    errors: list[str] = []
    warnings: list[str] = []
    for column in chart_plan.required_columns:
        if column and not _has_output_name(output_names, column):
            errors.append(f"SQL does not output chart required column: {column}")

    if chart_plan.x_dimension == "sexo" or chart_plan.series_dimension == "sexo":
        if _outputs_raw_sex_code(sql) and not _outputs_readable_sex_label(sql):
            warnings.append(
                "Chart by sexo should output human-readable labels, not only raw SEXO codes."
            )

    extra_columns = [
        name
        for name in output_names
        if chart_plan.required_columns and not any(_names_match(name, req) for req in chart_plan.required_columns)
    ]
    if len(extra_columns) > 2:
        warnings.append(
            "SQL outputs several extra columns beyond the chart contract: "
            + ", ".join(extra_columns[:6])
        )

    return ChartSqlValidation(is_valid=not errors, errors=errors, warnings=warnings)


def _outer_select_output_names(sql: str) -> list[str]:
    try:
        parsed = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return _fallback_select_aliases(sql)
    select = parsed if isinstance(parsed, exp.Select) else parsed.find(exp.Select)
    if select is None:
        return []
    output_names: list[str] = []
    for expression in select.expressions:
        alias = expression.alias_or_name
        if alias:
            output_names.append(alias.strip('"'))
    return output_names


def _fallback_select_aliases(sql: str) -> list[str]:
    match = re.search(r"\bselect\b(?P<select>.*?)\bfrom\b", sql, flags=re.I | re.S)
    if not match:
        return []
    names: list[str] = []
    for item in match.group("select").split(","):
        alias = re.search(r"\bas\s+\"?([A-Za-z_][\w]*)\"?\s*$", item.strip(), flags=re.I)
        if alias:
            names.append(alias.group(1))
        else:
            names.append(item.strip().split(".")[-1].strip('" '))
    return names


def _has_output_name(output_names: list[str], required: str) -> bool:
    return any(_names_match(name, required) for name in output_names)


def _names_match(name: str, required: str) -> bool:
    normalized_name = name.lower().strip('"')
    normalized_required = required.lower().strip('"')
    return (
        normalized_name == normalized_required
        or normalized_required in normalized_name
        or normalized_name in normalized_required
    )


def _outputs_raw_sex_code(sql: str) -> bool:
    text = sql.lower()
    return bool(re.search(r"\bsex[oa]?\b|\"sexo\"|\bsexo\b", text))


def _outputs_readable_sex_label(sql: str) -> bool:
    text = sql.lower()
    return (
        "join sexo" in text
        and ("descricao" in text or "descrição" in text)
        or "masculino" in text
        or "feminino" in text
    )

