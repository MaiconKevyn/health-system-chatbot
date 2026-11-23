from __future__ import annotations

import re
from pathlib import Path

import sqlglot
from sqlglot import expressions as exp

from .models import QuestionContract, SqlPlan, Stage1Context, ValidationResult
from .question_contract import build_question_contract
from .semantic_rules import applicable_semantic_rules
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

    try:
        scoped_errors = _unqualified_column_scope_errors(parsed, ctx, select_aliases)
    except Exception:
        scoped_errors = None
    if scoped_errors is not None:
        errors.extend(error for error in scoped_errors if error not in errors)
        return errors

    for column in parsed.find_all(exp.Column):
        column_name = column.name
        if not column_name or column_name == "*" or column.table:
            continue
        if column_name.upper() in select_aliases:
            continue
        if _resolve_column(column, ctx, aliases, tables) is None:
            key = column_name.upper()
            if key not in seen:
                seen.add(key)
                errors.append(f"Unknown or ambiguous column: {column_name}")

    return errors


def _scope_column_matches(scope, column_name: str, ctx: Stage1Context) -> tuple[int, bool]:
    """Count sources in this SELECT that expose ``column_name``.

    Returns (matches, open_source): open_source is True when a CTE/derived table
    projects ``*`` so its columns cannot be enumerated.
    """
    matches = 0
    open_source = False
    for _, source in scope.selected_sources.values():
        if isinstance(source, exp.Table):
            if _column_type(ctx, source.name, column_name) is not None:
                matches += 1
            elif source.name not in ctx.tables:
                open_source = True  # unknown table is reported elsewhere
            continue
        source_expression = getattr(source, "expression", None)
        if not isinstance(source_expression, exp.Query):
            open_source = True
            continue
        if source_expression.is_star:
            open_source = True
        if column_name.upper() in {name.upper() for name in source_expression.named_selects}:
            matches += 1
    return matches, open_source


def _unqualified_column_scope_errors(
    parsed: exp.Expression,
    ctx: Stage1Context,
    select_aliases: set[str],
) -> list[str]:
    """Resolve unqualified columns per SELECT scope, the way DuckDB binds them.

    Resolving against every table in the whole statement flagged valid SQL as
    ambiguous: in sihrd9, counting births needs internacao and
    internacao_procedimento (both have N_AIH), so a CTE or IN-subquery that
    selects N_AIH from only one of them was rejected.
    """
    from sqlglot.optimizer.scope import traverse_scope

    errors: list[str] = []
    seen: set[str] = set()
    for scope in traverse_scope(parsed):
        using_columns = {
            identifier.name.upper()
            for join in scope.expression.args.get("joins") or []
            for identifier in join.args.get("using") or []
        }
        for column in scope.unqualified_columns:
            # sqlglot also lists columns of IN-subqueries on the outer scope;
            # judge each column only in the SELECT that directly contains it.
            if column.find_ancestor(exp.Select) is not scope.expression:
                continue
            name = column.name
            if not name or name == "*" or name.upper() in select_aliases:
                continue
            matches, open_source = _scope_column_matches(scope, name, ctx)
            if matches > 1 and name.upper() in using_columns:
                matches = 1  # USING merges the join key into one column
            if matches == 0 and not open_source:
                parent = scope.parent
                while parent is not None and matches == 0 and not open_source:
                    matches, open_source = _scope_column_matches(parent, name, ctx)
                    parent = parent.parent
            if matches == 1 or (matches == 0 and open_source):
                continue
            key = name.upper()
            if key in seen:
                continue
            seen.add(key)
            errors.append(
                f"Ambiguous column: {name}; qualify it with a table alias."
                if matches > 1
                else f"Unknown column: {name}"
            )
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


_TIME_UNIT_NAMES: dict[str, set[str]] = {
    "year": {"YEAR", "YEARS", "Y", "YR", "YRS"},
    "quarter": {"QUARTER", "QUARTERS"},
    "month": {"MONTH", "MONTHS", "MON", "MONS"},
}
_TIME_PART_FUNCTIONS: dict[type[exp.Expression], str] = {
    exp.Year: "year",
    exp.Quarter: "quarter",
    exp.Month: "month",
}
_DATE_PART_FUNCTION_NAMES = {"DATE_PART", "DATEPART"}
_CALENDAR_GRAIN_COLUMNS = {"ANO": "year", "NU_ANO": "year", "TRIMESTRE": "quarter", "MES": "month"}


def _time_unit(name: str) -> str | None:
    upper = name.upper()
    return next((unit for unit, names in _TIME_UNIT_NAMES.items() if upper in names), None)


def _node_time_unit(node: exp.Expression) -> str | None:
    if type(node) in _TIME_PART_FUNCTIONS:
        return _TIME_PART_FUNCTIONS[type(node)]
    if isinstance(node, exp.Extract):
        return _time_unit(node.this.name)
    if isinstance(node, (exp.TimestampTrunc, exp.DateTrunc)):
        return _time_unit(node.text("unit"))
    if isinstance(node, exp.Anonymous) and node.name.upper() in _DATE_PART_FUNCTION_NAMES:
        return _time_unit(node.expressions[0].name) if node.expressions else None
    if isinstance(node, exp.TimeToStr):
        time_format = node.text("format")
        if re.search(r"%[mbB]", time_format):
            return "month"
        return "year" if re.search(r"%[Yy]", time_format) else None
    if isinstance(node, exp.Column):
        return _CALENDAR_GRAIN_COLUMNS.get(node.name.upper())
    return None


def _time_units_anywhere(parsed: exp.Expression) -> set[str]:
    return {unit for node in parsed.walk() if (unit := _node_time_unit(node))}


def _walk_outside_subqueries(root: exp.Expression):
    return root.walk(
        prune=lambda node: node is not root and isinstance(node, (exp.Select, exp.Subquery))
    )


def _output_time_units(parsed: exp.Expression) -> set[str]:
    """Calendar units that shape result rows; WHERE/HAVING filters do not count."""
    inner_aliases: dict[str, list[exp.Expression]] = {}
    for select in parsed.find_all(exp.Select):
        if select is parsed:
            continue
        for projection in select.expressions:
            if isinstance(projection, exp.Alias):
                inner_aliases.setdefault(projection.alias.upper(), []).append(projection.this)

    group = parsed.args.get("group")
    pending = [*parsed.expressions, *(group.expressions if group else [])]
    if any(
        isinstance(projection, exp.Star)
        or (isinstance(projection, exp.Column) and projection.name == "*")
        for projection in parsed.expressions
    ):
        pending.extend(node for nodes in inner_aliases.values() for node in nodes)

    units: set[str] = set()
    followed: set[str] = set()
    while pending:
        for node in _walk_outside_subqueries(pending.pop()):
            if unit := _node_time_unit(node):
                units.add(unit)
            if isinstance(node, exp.Column) and node.name.upper() not in followed:
                followed.add(node.name.upper())
                pending.extend(inner_aliases.get(node.name.upper(), []))
    return units


def _contract_policy_findings(
    safe_sql: str,
    contract: QuestionContract,
    parsed: exp.Expression,
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    upper = safe_sql.upper()
    errors: list[str] = []
    warnings: list[str] = []
    findings: list[dict[str, str]] = []

    for source in contract.required_sources:
        if re.search(rf"\b{re.escape(source.upper())}\b", upper) is None:
            errors.append(f"Required source missing from SQL: {source}")
            findings.append(
                {
                    "layer": "contract",
                    "code": "required_source_missing",
                    "detail": source,
                }
            )

    explicit_n = contract.ranking.n
    has_limit = bool(re.search(r"\bLIMIT\s+\d+\b", upper))
    has_rank = bool(re.search(r"\b(?:ROW_NUMBER|RANK|DENSE_RANK)\s*\(", upper))
    has_rank_filter = bool(
        explicit_n is not None
        and re.search(rf"\b(?:RN|RANK\w*)\s*<=?\s*{explicit_n}\b", upper)
    )
    has_exact_limit = bool(
        explicit_n is not None
        and re.search(rf"\bLIMIT\s+{explicit_n}\b", upper)
    )
    if explicit_n is not None and not (has_exact_limit or (has_rank and has_rank_filter)):
        errors.append(
            f"Question explicitly requests top {explicit_n}, but SQL does not enforce that cardinality."
        )
        findings.append(
            {"layer": "contract", "code": "explicit_top_n_missing", "detail": str(explicit_n)}
        )
    if explicit_n is None and has_limit:
        warnings.append("SQL adds LIMIT although the question contract has no explicit top-N.")
        findings.append(
            {"layer": "contract", "code": "implicit_limit", "detail": "LIMIT present"}
        )

    has_ranking_partition = bool(
        re.search(
            r"\b(?:ROW_NUMBER|RANK|DENSE_RANK)\s*\([^)]*\)\s*OVER\s*\([^)]*PARTITION\s+BY",
            upper,
            re.S,
        )
    )
    if explicit_n is not None and contract.ranking.partition_by and not has_ranking_partition:
        errors.append(
            "Question explicitly requests top-N per group, but SQL has no partitioned ranking."
        )
        findings.append(
            {
                "layer": "contract",
                "code": "partitioned_ranking_missing",
                "detail": ",".join(contract.ranking.partition_by),
            }
        )
    if explicit_n is not None and not contract.ranking.partition_by and has_ranking_partition:
        warnings.append(
            "SQL partitions a ranking although no per-group partition is explicit in the question."
        )
        findings.append(
            {"layer": "contract", "code": "implicit_ranking_partition", "detail": "PARTITION BY"}
        )

    if contract.ranking.minimum_support is not None:
        threshold = contract.ranking.minimum_support
        if str(threshold) not in upper or not re.search(r"\b(?:HAVING|WHERE)\b", upper):
            errors.append(
                f"Question explicitly requires minimum support {threshold}, but SQL does not enforce it."
            )
            findings.append(
                {"layer": "contract", "code": "minimum_support_missing", "detail": str(threshold)}
            )

    if contract.time.basis == "admission_date" and "DT_SAIDA" in upper and "DT_INTER" not in upper:
        errors.append("Question requires admission-date basis, but SQL uses discharge date.")
    elif contract.time.basis == "discharge_date" and "DT_INTER" in upper and "DT_SAIDA" not in upper:
        errors.append("Question requires discharge-date basis, but SQL uses admission date.")
    elif contract.time.basis == "unresolved" and ("DT_INTER" in upper or "DT_SAIDA" in upper):
        warnings.append("SQL selected a date basis while the question contract remains unresolved.")
        findings.append(
            {"layer": "contract", "code": "date_basis_assumption", "detail": "unresolved"}
        )

    if (
        contract.time.grain in _TIME_UNIT_NAMES
        and contract.time.grain not in _time_units_anywhere(parsed)
    ):
        errors.append(
            f"Question requires temporal grain {contract.time.grain}, but SQL does not project it."
        )
        findings.append(
            {"layer": "contract", "code": "temporal_grain_missing", "detail": contract.time.grain}
        )
    if (
        contract.time.grain in {"quarter", "month"}
        and "year" in _output_time_units(parsed)
        and not re.search(r"\b(?:por|cada)\s+ano\b", normalize_text(contract.population))
    ):
        errors.append(
            f"SQL adds year to a {contract.time.grain}-of-year result although year is not requested."
        )
        findings.append(
            {"layer": "contract", "code": "temporal_grain_oversegmented", "detail": "year"}
        )

    if "dimension_coverage_audit" in contract.concepts:
        has_unmatched = "SEM_CORRESPONDENCIA" in upper or "UNMATCHED" in upper
        has_total = bool(
            re.search(r"COUNT\s*\(\s*\*\s*\)\s+AS\s+(?:INTERNACOES|TOTAL\w*)\b", upper)
        )
        if not (has_unmatched and has_total):
            warnings.append(
                "Dimension coverage audits should expose both unmatched and total counts."
            )
        if "WHERE" in upper and " IS NULL" in upper and "COUNT(*) FILTER" not in upper:
            warnings.append(
                "Dimension coverage audit drops the full denominator in WHERE; use a filtered aggregate."
            )

    return errors, warnings, findings


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


def _binder_errors(safe_sql: str, db_path: Path | None) -> list[str]:
    if db_path is None or not db_path.exists():
        return []
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        con.execute("EXPLAIN " + safe_sql)
    except Exception as exc:
        return [f"DuckDB binder error: {exc}"]
    finally:
        con.close()
    return []


def _cte_aggregate_aliases(parsed: exp.Expression) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for cte in parsed.find_all(exp.CTE):
        aliases: set[str] = set()
        select = cte.this
        if isinstance(select, exp.Select):
            for expression in select.expressions:
                if isinstance(expression, exp.Alias) and expression.this.find(exp.AggFunc):
                    aliases.add(expression.alias.upper())
        result[cte.alias] = aliases
    return result


def _relation_aliases(parsed: exp.Expression) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for table in parsed.find_all(exp.Table):
        aliases[table.name] = table.name
        if table.alias:
            aliases[table.alias] = table.name
    return aliases


def _grain_lineage_findings(
    parsed: exp.Expression,
) -> tuple[list[str], list[dict[str, str]]]:
    errors: list[str] = []
    findings: list[dict[str, str]] = []
    aggregate_aliases = _cte_aggregate_aliases(parsed)
    relation_aliases = _relation_aliases(parsed)

    for join in parsed.find_all(exp.Join):
        on = join.args.get("on")
        if on is None:
            continue
        for equality in on.find_all(exp.EQ):
            for side in (equality.left, equality.right):
                if not isinstance(side, exp.Column) or not side.table:
                    continue
                relation = relation_aliases.get(side.table, side.table)
                if side.name.upper() in aggregate_aliases.get(relation, set()):
                    errors.append(
                        "Join uses an aggregated measure as a key; preserve the entity key "
                        f"instead: {side.sql(dialect='duckdb')}"
                    )
                    findings.append(
                        {
                            "layer": "grain",
                            "code": "join_on_aggregate_measure",
                            "detail": side.sql(dialect="duckdb"),
                        }
                    )

    for select in parsed.find_all(exp.Select):
        source_names: set[str] = set()
        from_expression = select.args.get("from_")
        if from_expression is not None and isinstance(from_expression.this, exp.Table):
            source_names.add(from_expression.this.name)
        for join in select.args.get("joins") or []:
            if isinstance(join.this, exp.Table):
                source_names.add(join.this.name)
        inherited_aggregates = set().union(
            *(aggregate_aliases.get(name, set()) for name in source_names)
        ) if source_names else set()
        for percentile in select.find_all(exp.PercentileCont, exp.PercentileDisc):
            argument = percentile.this
            if isinstance(argument, exp.Column) and argument.name.upper() in inherited_aggregates:
                errors.append(
                    "Percentile is computed over a previously aggregated measure; compute "
                    "the percentile at the event grain before the final grouping."
                )
                findings.append(
                    {
                        "layer": "grain",
                        "code": "percentile_on_aggregated_measure",
                        "detail": argument.name,
                    }
                )
    return errors, findings


def _semantic_rule_findings(
    safe_sql: str,
    ctx: Stage1Context,
    contract: QuestionContract,
) -> tuple[list[str], list[dict[str, str]]]:
    errors: list[str] = []
    findings: list[dict[str, str]] = []
    rules = {rule.id: rule for rule in ctx.semantic_rules}
    for rule_id in contract.semantic_rule_ids:
        rule = rules.get(rule_id)
        if rule is None or rule.status != "active":
            continue
        for pattern in rule.forbidden_sql_patterns:
            if re.search(pattern, safe_sql, re.I):
                errors.append(
                    f"SQL violates semantic rule {rule.id}: forbidden pattern {pattern}"
                )
                findings.append(
                    {"layer": "semantic_rule", "code": "forbidden_pattern", "detail": rule.id}
                )
        if rule.required_sql_any and not any(
            re.search(pattern, safe_sql, re.I) for pattern in rule.required_sql_any
        ):
            errors.append(
                f"SQL does not implement active semantic rule {rule.id} from "
                f"{rule.provenance.reference}."
            )
            findings.append(
                {"layer": "semantic_rule", "code": "required_predicate_missing", "detail": rule.id}
            )
        missing_all = [
            pattern
            for pattern in rule.required_sql_all
            if not re.search(pattern, safe_sql, re.I)
        ]
        if missing_all:
            errors.append(
                f"SQL does not implement all predicates required by semantic rule {rule.id} "
                f"from {rule.provenance.reference}."
            )
            findings.append(
                {
                    "layer": "semantic_rule",
                    "code": "required_predicates_incomplete",
                    "detail": rule.id,
                }
            )
    return errors, findings


def validate_sql(
    sql: str,
    ctx: Stage1Context,
    *,
    question: str = "",
    plan: SqlPlan | None = None,
    question_contract: QuestionContract | None = None,
    db_path: Path | None = None,
) -> ValidationResult:
    safe_sql = _strip_sql(sql)
    errors = []
    warnings = []
    findings: list[dict[str, str]] = []
    probe_stats: list[dict[str, object]] = []
    contract = question_contract or build_question_contract(question)
    if not contract.semantic_rule_ids:
        rules = applicable_semantic_rules(contract, ctx.semantic_rules)
        contract = contract.model_copy(
            update={"semantic_rule_ids": [rule.id for rule in rules]}
        )

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
            lineage_errors, lineage_findings = _grain_lineage_findings(parsed)
            errors.extend(lineage_errors)
            findings.extend(lineage_findings)
            warnings.extend(
                _dimension_description_required_errors(
                    safe_sql=safe_sql,
                    question=question,
                    tables=tables,
                )
            )
            contract_errors, contract_warnings, contract_findings = _contract_policy_findings(
                safe_sql,
                contract,
                parsed,
            )
            errors.extend(contract_errors)
            warnings.extend(contract_warnings)
            findings.extend(contract_findings)
            rule_errors, rule_findings = _semantic_rule_findings(
                safe_sql,
                ctx,
                contract,
            )
            errors.extend(rule_errors)
            findings.extend(rule_findings)
            warnings.extend(_catalog_decision_warnings(safe_sql, plan))
            errors.extend(_binder_errors(safe_sql, db_path))

            if (
                contract.cumulative_threshold_percent is not None
                and " OVER " in f" {safe_sql.upper()} "
                and "LAG(" not in safe_sql.upper()
                and " OR " not in f" {safe_sql.upper()} "
            ):
                warnings.append(
                    "Cumulative coverage SQL must include the first row that crosses the threshold; "
                    "a simple cumulative <= threshold filter may under-cover."
                )
                findings.append(
                    {
                        "layer": "grain",
                        "code": "cumulative_crossing_row_unverified",
                        "detail": str(contract.cumulative_threshold_percent),
                    }
                )

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
        if uses_policy_columns:
            probe_stats.append(
                {
                    "type": "join_policy_coverage",
                    "left": policy.left,
                    "right": policy.right,
                    "left_rows": policy.left_rows,
                    "matched_rows": policy.matched_rows,
                    "unmatched_rows": policy.unmatched_rows,
                    "match_rate_non_null": policy.match_rate_non_null,
                    "confidence": policy.confidence,
                    "scope": "catalog_profile_before_query_filters",
                }
            )

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

    if "internacao_procedimento" in tables and "COUNT(*)" in upper:
        warnings.append(
            "COUNT(*) over internacao_procedimento counts procedure occurrences (long-stay "
            "AIHs repeat rows); use COUNT(DISTINCT N_AIH) or EXISTS to count hospitalizations."
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
            findings=findings,
            probe_stats=probe_stats,
        )

    return ValidationResult(
        is_valid=True,
        severity="warning" if warnings else "info",
        errors=[],
        warnings=warnings,
        safe_sql=safe_sql,
        findings=findings,
        probe_stats=probe_stats,
    )
