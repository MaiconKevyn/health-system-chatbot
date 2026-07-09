from __future__ import annotations

import re

import sqlglot
from sqlglot import expressions as exp

from .models import SqlPlan, Stage1Context, ValidationResult
from .schema_linking import (
    DIMENSION_LINKS,
    description_required_for_link,
    question_matches_link,
)
from .text import normalize_text


BLOCKED_KEYWORDS = {
    "ALTER",
    "ATTACH",
    "CHECKPOINT",
    "COPY",
    "CREATE",
    "DELETE",
    "DROP",
    "EXPORT",
    "INSERT",
    "INSTALL",
    "LOAD",
    "PRAGMA",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
}

FILE_ACCESS_PATTERNS = (
    "read_csv",
    "read_json",
    "read_parquet",
    "httpfs",
    "secret",
)

NUMERIC_TYPES = {
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "UBIGINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UHUGEINT",
    "HUGEINT",
    "FLOAT",
    "DOUBLE",
    "REAL",
    "DECIMAL",
    "NUMERIC",
}

VALID_UFS = {
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
}


def _strip_sql(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def _keyword_errors(sql: str) -> list[str]:
    upper = sql.upper()
    errors = []
    for keyword in sorted(BLOCKED_KEYWORDS):
        if re.search(rf"\b{keyword}\b", upper):
            errors.append(f"Blocked SQL keyword: {keyword}")
    lower = sql.lower()
    for pattern in FILE_ACCESS_PATTERNS:
        if pattern in lower:
            errors.append(f"Blocked file/extension access pattern: {pattern}")
    return errors


def _cte_names(parsed: exp.Expression) -> set[str]:
    names = set()
    for cte in parsed.find_all(exp.CTE):
        if cte.alias:
            names.add(cte.alias)
    return names


def _referenced_tables(parsed: exp.Expression) -> set[str]:
    ctes = _cte_names(parsed)
    tables = set()
    for table in parsed.find_all(exp.Table):
        name = table.name
        if name and name not in ctes:
            tables.add(name)
    return tables


def _table_aliases(parsed: exp.Expression) -> dict[str, str]:
    aliases: dict[str, str] = {}
    ctes = _cte_names(parsed)
    for table in parsed.find_all(exp.Table):
        if not table.name or table.name in ctes:
            continue
        aliases[table.name] = table.name
        if table.alias:
            aliases[table.alias] = table.name
    return aliases


def _column_type(ctx: Stage1Context, table_name: str, column_name: str) -> tuple[str, str] | None:
    table = ctx.tables.get(table_name)
    if not table:
        return None
    for candidate, data_type in table.column_types.items():
        if candidate.upper() == column_name.upper():
            return candidate, data_type
    return None


def _resolve_column(
    column: exp.Column,
    ctx: Stage1Context,
    aliases: dict[str, str],
    tables: set[str],
) -> tuple[str, str, str] | None:
    qualifier = column.table
    if qualifier:
        table_name = aliases.get(qualifier, qualifier)
        typed_column = _column_type(ctx, table_name, column.name)
        if typed_column:
            return table_name, typed_column[0], typed_column[1]
        return None

    matches = []
    for table_name in tables:
        typed_column = _column_type(ctx, table_name, column.name)
        if typed_column:
            matches.append((table_name, typed_column[0], typed_column[1]))
    return matches[0] if len(matches) == 1 else None


def _select_aliases(parsed: exp.Expression) -> set[str]:
    aliases = set()
    for alias in parsed.find_all(exp.Alias):
        if alias.alias:
            aliases.add(alias.alias.upper())
    return aliases


def _unknown_column_errors(
    parsed: exp.Expression,
    ctx: Stage1Context,
    tables: set[str],
) -> list[str]:
    aliases = _table_aliases(parsed)
    select_aliases = _select_aliases(parsed)
    cte_names = _cte_names(parsed)
    errors: list[str] = []
    seen: set[str] = set()

    for column in parsed.find_all(exp.Column):
        column_name = column.name
        if not column_name or column_name == "*":
            continue

        qualifier = column.table
        if qualifier:
            table_name = aliases.get(qualifier, qualifier)
            if table_name in cte_names:
                continue
            if table_name in ctx.tables and _column_type(ctx, table_name, column_name) is None:
                key = f"{table_name}.{column_name}"
                if key not in seen:
                    seen.add(key)
                    errors.append(f"Unknown column: {table_name}.{column_name}")
            continue

        if column_name.upper() in select_aliases:
            continue
        if _resolve_column(column, ctx, aliases, tables) is None:
            key = column_name.upper()
            if key not in seen:
                seen.add(key)
                errors.append(f"Unknown or ambiguous column: {column_name}")

    return errors


def _is_numeric_type(data_type: str) -> bool:
    upper = data_type.upper()
    return upper in NUMERIC_TYPES or upper.startswith("DECIMAL(") or upper.startswith("NUMERIC(")


def _literal_preview(literal: exp.Literal) -> str:
    value = str(literal.this)
    if len(value) > 40:
        value = value[:37] + "..."
    return value


def _text_literal_numeric_type_errors(
    parsed: exp.Expression,
    ctx: Stage1Context,
    tables: set[str],
) -> list[str]:
    aliases = _table_aliases(parsed)
    errors: list[str] = []
    seen: set[str] = set()

    def add_error(column: exp.Column, literal: exp.Literal) -> None:
        resolved = _resolve_column(column, ctx, aliases, tables)
        if not resolved:
            return
        table_name, column_name, data_type = resolved
        if not _is_numeric_type(data_type):
            return
        key = f"{table_name}.{column_name}:{literal.this}"
        if key in seen:
            return
        seen.add(key)
        errors.append(
            f"Column {table_name}.{column_name} has {data_type} type and cannot be "
            f"compared to text literal '{_literal_preview(literal)}'. "
            "For city names, join municipios and filter municipios.NO_MUNICIPIO/SG_UF."
        )

    comparison_types = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
    for comparison_type in comparison_types:
        for comparison in parsed.find_all(comparison_type):
            left = comparison.left
            right = comparison.right
            if isinstance(left, exp.Column) and isinstance(right, exp.Literal) and right.is_string:
                add_error(left, right)
            if isinstance(right, exp.Column) and isinstance(left, exp.Literal) and left.is_string:
                add_error(right, left)

    for in_expression in parsed.find_all(exp.In):
        target = in_expression.this
        if not isinstance(target, exp.Column):
            continue
        for expression in in_expression.expressions:
            if isinstance(expression, exp.Literal) and expression.is_string:
                add_error(target, expression)

    return errors


def _has_left_join_for(sql: str, table_name: str) -> bool:
    return bool(re.search(rf"\bLEFT\s+(?:OUTER\s+)?JOIN\s+{re.escape(table_name)}\b", sql, re.I))


def _has_explicit_mapped_scope(question: str, plan: SqlPlan | None) -> bool:
    chunks = [question]
    if plan:
        chunks.extend(plan.caveats)
        chunks.extend(plan.join_assumptions)
        chunks.append(plan.question)
    text = normalize_text(" ".join(chunks))
    return any(
        token in text
        for token in (
            "mapeado",
            "mapeada",
            "mapped",
            "restrito",
            "universo mapeado",
            "denominador socioeconomico",
        )
    )


def _asks_for_raw_code_without_description(question: str) -> bool:
    text = normalize_text(question)
    tokens = set(text.split())
    asks_code = bool(tokens & {"codigo", "codigos"})
    asks_description = bool(tokens & {"descricao", "descricoes", "nome", "nomes"})
    return asks_code and not asks_description


def _description_column_names(description_column: str) -> set[str]:
    names = set()
    for chunk in re.split(r"[/,]", description_column):
        chunk = chunk.strip()
        if not chunk:
            continue
        names.add(chunk.split(".")[-1].upper())
    return names


def _dimension_description_required_errors(
    *,
    safe_sql: str,
    question: str,
    tables: set[str],
) -> list[str]:
    errors = []
    upper = safe_sql.upper()
    for link in DIMENSION_LINKS:
        if not question_matches_link(question, link):
            continue
        if not description_required_for_link(question, link):
            continue
        if link.fact_table not in tables:
            continue

        description_names = _description_column_names(link.description_column)
        has_dimension_table = link.dimension_table in tables
        has_description = any(name in upper for name in description_names)
        if has_dimension_table and has_description:
            continue

        errors.append(
            "Question asks for business-readable dimension "
            f"'{link.business_name}'. Join {link.dimension_key} and return "
            f"{link.description_column}; do not group only by raw code {link.fact_column}."
        )
    return errors


def _shape_policy_errors(safe_sql: str, question: str) -> list[str]:
    text = normalize_text(question)
    tokens = set(text.split())
    upper = safe_sql.upper()
    errors = []

    if any(term in text for term in ("auditoria", "sem correspondencia", "nao mapeado", "orfa")):
        if "SEM_CORRESPONDENCIA" in upper and not re.search(
            r"COUNT\s*\(\s*\*\s*\)\s+AS\s+INTERNACOES\b",
            upper,
        ):
            errors.append(
                "Audit dimension coverage queries must return both sem_correspondencia "
                "and COUNT(*) AS internacoes."
            )
        if "WHERE" in upper and " IS NULL" in upper and "COUNT(*) FILTER" not in upper:
            errors.append(
                "Audit dimension coverage queries must keep the full denominator. "
                "Use COUNT(*) FILTER (WHERE dimension.key IS NULL) AS sem_correspondencia "
                "instead of moving the NULL check to WHERE."
            )

    if tokens & {"mais", "maiores", "ranking", "top"} and "LIMIT" not in upper:
        errors.append("Ranking queries must include LIMIT 20 unless the user requested another limit.")

    if "mix" in tokens and "percentual" not in tokens and (
        "PERCENT" in upper or "100.0" in upper or "100 *" in upper
    ):
        errors.append("Mix queries should not include percentage columns unless explicitly requested.")
    if "mix de complexidade por carater" in text and not re.search(
        r"ORDER\s+BY\s+INTERNACOES\s+DESC\b",
        upper,
    ):
        errors.append("Mix de complexidade por carater must be ordered by internacoes DESC.")

    if ("cid c" in text or "cid-c" in text) and "por ano" in text and "FILTER" in upper:
        errors.append(
            "CID C time series should filter matching events in WHERE before GROUP BY, "
            "not use COUNT(*) FILTER that preserves unrelated years."
        )

    if "contraceptivo 1" in text and "SEM CORRESPONDENCIA" in upper and "auditoria" not in text:
        errors.append(
            "Contraceptive type distributions should not add an unmapped bucket unless this is an audit question."
        )
    if (
        "contraceptivo 1" in text
        and "LEFT JOIN CONTRACEPTIVOS" in upper
        and "auditoria" not in text
    ):
        errors.append(
            "Contraceptive type distributions should use JOIN contraceptivos; "
            "LEFT JOIN adds an extra NULL/unmapped bucket unless this is an audit question."
        )

    if (
        ("denominador socioeconomico" in text or "populacao socioeconomica" in text)
        and "registros" not in text
        and re.search(r"COUNT\s*\(\s*\*\s*\)\s+AS\s+REGISTROS\b", upper)
    ):
        errors.append(
            "Socioeconomic population by UF/year should not add COUNT(*) AS registros unless requested."
        )

    return errors


def _catalog_decision_warnings(safe_sql: str, plan: SqlPlan | None) -> list[str]:
    if plan is None or not plan.catalog_decisions:
        return []
    upper = safe_sql.upper()
    warnings: list[str] = []
    for decision in plan.catalog_decisions:
        selected_filter = decision.selected_filter.upper()
        if "DS_GRUPO" in selected_filter and "DIAG_PRINC IN" in upper and "DS_GRUPO" not in upper:
            warnings.append(
                "SQL appears to transform a CID group catalog decision into a short "
                "DIAG_PRINC IN list. Prefer joining cid and filtering the selected DS_GRUPO."
            )
        if "DS_CAPITULO" in selected_filter and "DIAG_PRINC IN" in upper and "DS_CAPITULO" not in upper:
            warnings.append(
                "SQL appears to transform a CID chapter catalog decision into a short "
                "DIAG_PRINC IN list. Prefer joining cid and filtering the selected DS_CAPITULO."
            )
    return warnings


def validate_sql(
    sql: str,
    ctx: Stage1Context,
    *,
    question: str = "",
    plan: SqlPlan | None = None,
) -> ValidationResult:
    safe_sql = _strip_sql(sql)
    errors = []
    warnings = []

    if not safe_sql:
        return ValidationResult(is_valid=False, severity="error", errors=["SQL is empty"])

    errors.extend(_keyword_errors(safe_sql))
    if ";" in safe_sql:
        errors.append("Multiple SQL statements are not allowed")

    try:
        parsed_statements = sqlglot.parse(safe_sql, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        return ValidationResult(is_valid=False, severity="error", errors=[f"SQL parse error: {exc}"])

    if len(parsed_statements) != 1:
        errors.append("Exactly one SQL statement is required")
        parsed = parsed_statements[0] if parsed_statements else None
    else:
        parsed = parsed_statements[0]

    if parsed is not None and not isinstance(parsed, exp.Select):
        errors.append(f"Only SELECT/WITH statements are allowed, got {parsed.key}")

    tables: set[str] = set()
    if parsed is not None:
        tables = _referenced_tables(parsed)
        unknown = sorted(table for table in tables if table not in ctx.table_names)
        if unknown:
            errors.append(f"Unknown or unsupported table(s): {', '.join(unknown)}")
        else:
            errors.extend(_unknown_column_errors(parsed, ctx, tables))
            errors.extend(_text_literal_numeric_type_errors(parsed, ctx, tables))
            warnings.extend(
                _dimension_description_required_errors(
                    safe_sql=safe_sql,
                    question=question,
                    tables=tables,
                )
            )
            warnings.extend(_shape_policy_errors(safe_sql, question))
            warnings.extend(_catalog_decision_warnings(safe_sql, plan))

    for table in tables:
        if table.startswith("main_dbt_test__audit") or table.startswith("dbt_"):
            warnings.append(
                f"Audit table referenced; confirm this is intended for the question: {table}"
            )

    question_text = normalize_text(question)
    is_audit_question = any(
        token in question_text
        for token in (
            "auditoria",
            "qualidade",
            "inconsistencia",
            "inconsistencias",
            "sem correspondencia",
            "nao mapeado",
            "orfaos",
        )
    )

    for policy in ctx.join_policies:
        left_table = policy.left.split(".")[0]
        right_table = policy.right.split(".")[0]
        if left_table not in tables or right_table not in tables:
            continue

        left_col = policy.left.split(".")[-1]
        right_col = policy.right.split(".")[-1]
        uses_policy_columns = left_col.upper() in safe_sql.upper() and right_col.upper() in safe_sql.upper()

        if policy.confidence == "rejected" and uses_policy_columns and not is_audit_question:
            has_unmapped_bucket = (
                _has_left_join_for(safe_sql, right_table)
                and (
                    "SEM CORRESPONDENCIA" in safe_sql.upper()
                    or "SEM CORRESPONDENCIA" in question.upper()
                    or "QUANDO HOUVER CORRESPONDENCIA" in question.upper()
                )
            )
            if has_unmapped_bucket:
                warnings.append(
                    f"Rejected relationship used only with LEFT JOIN/unmapped bucket: {policy.left} -> {policy.right}"
                )
            else:
                warnings.append(
                    f"Rejected relationship cannot be used for business answers: {policy.left} -> {policy.right}"
                )

        if policy.accepted_usage_policy == "left_join_or_explicit_mapped_scope_required":
            has_left_join = _has_left_join_for(safe_sql, right_table)
            if uses_policy_columns and not has_left_join and not _has_explicit_mapped_scope(question, plan):
                warnings.append(
                    f"Join requires LEFT JOIN or explicit mapped scope: {policy.left} -> {policy.right}"
                )

    upper = safe_sql.upper()
    if _asks_for_raw_code_without_description(question) and "DESCRICAO" in upper:
        warnings.append(
            "Question asks for raw codes; do not include DESCRICAO/name columns unless requested."
        )

    if "INTERNACAO_PROCEDIMENTO" in upper and "INTERNACOES" in upper and "COUNT(*)" in upper:
        warnings.append(
            "Query joins procedures and admissions; confirm whether the unit is procedure occurrence or hospitalization."
        )

    if "SG_UF" in upper and "VALID_UF" not in upper and not all(f"'{uf}'" in upper for uf in list(VALID_UFS)[:3]):
        warnings.append("Query references SG_UF; ensure invalid numeric SG_UF codes are excluded when counting UFs.")

    if "LIMIT" not in upper and not re.search(r"\b(COUNT|SUM|AVG|MIN|MAX|QUANTILE|ROUND)\s*\(", upper):
        warnings.append("Exploratory row-returning query has no LIMIT.")

    if errors:
        return ValidationResult(
            is_valid=False,
            severity="error",
            errors=errors,
            warnings=warnings,
            required_clarification="A consulta precisa ser corrigida antes de executar.",
        )

    return ValidationResult(
        is_valid=True,
        severity="warning" if warnings else "info",
        errors=[],
        warnings=warnings,
        safe_sql=safe_sql,
    )
