#!/usr/bin/env python3
"""Regenerate the runtime schema artifacts in docs/generated from a DuckDB file.

The chatbot loads table metadata, the column catalog, column profiles and the
join policy from docs/generated (see ``artifacts.load_stage1_context``). Run this
whenever the database is replaced so the prompts, validator and join policies
describe the database that is actually queried:

    python scripts/refresh_db_artifacts.py            # uses CHATBOT_DB_PATH
    python scripts/refresh_db_artifacts.py --db /path/to/sihrd9.duckdb

Only the files consumed at runtime (plus their direct companions) are written;
the Stage 1 ground-truth pipeline lives in scripts/sihrd5_stage1.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from health_system_chatbot.config import load_config  # noqa: E402

GENERATED_DIR = ROOT / "docs" / "generated"

FACT_TABLES = {"internacao", "internacao_procedimento"}
RUNTIME_EXCLUDED_PREFIXES = ("stg_", "dbt_")
EXACT_PROFILE_MAX_ROWS = 100_000

BUSINESS_CRITICAL_FACT_COLUMNS = {
    ("internacao", "N_AIH"),
    ("internacao", "CNES"),
    ("internacao", "MUNIC_RES"),
    ("internacao", "DIAG_PRINC"),
    ("internacao", "DT_INTER"),
    ("internacao", "DT_SAIDA"),
    ("internacao", "VAL_TOT"),
    ("internacao", "MORTE"),
    ("internacao", "COD_IDADE"),
    ("internacao_procedimento", "id_atendimento"),
    ("internacao_procedimento", "N_AIH"),
    ("internacao_procedimento", "PROC_REA"),
}

# (left_table, left_key, right_table, right_key, business meaning)
# CONTRACEP1/2 -> contraceptivos is left out on purpose: code 0 ("nao informado")
# covers ~99% of rows, which would label the dimension "rejected" and steer the
# agent away from legitimate LEFT JOIN distributions.
RELATIONSHIPS = [
    ("internacao", "CNES", "hospital", "CNES", "Hospital de atendimento pela chave CNES"),
    ("hospital", "MUNIC_MOV", "municipios", "CO_MUNICIPIO_6D", "Municipio do estabelecimento"),
    ("internacao", "MUNIC_RES", "municipios", "CO_MUNICIPIO_6D", "Municipio de residencia do usuario"),
    ("internacao", "SEXO", "sexo", "SEXO", "Sexo do usuario"),
    ("internacao", "RACA_COR", "raca_cor", "RACA_COR", "Raca/cor informada"),
    ("internacao", "ETNIA", "etnia", "ETNIA", "Etnia informada"),
    ("internacao", "NACIONAL", "nacionalidade", "NACIONAL", "Nacionalidade"),
    ("internacao", "INSTRU", "instrucao", "INSTRU", "Instrucao/escolaridade"),
    ("internacao", "VINCPREV", "vincprev", "VINCPREV", "Vinculo previdenciario"),
    ("internacao", "CAR_INT", "car_int", "CAR_INT", "Carater da internacao"),
    ("internacao", "ESPEC", "especialidade", "ESPEC", "Especialidade/leito"),
    ("internacao", "COMPLEX", "complexidade", "COMPLEX", "Complexidade do atendimento"),
    ("internacao", "MARCA_UTI", "marca_uti", "MARCA_UTI", "Marcador/tipo de UTI"),
    ("internacao", "CBOR", "cbor", "CBOR", "Ocupacao CBO-R"),
    ("internacao", "DIAG_PRINC", "cid", "CID", "Diagnostico principal CID"),
    ("internacao", "DIAG_SECUN", "cid", "CID", "Diagnostico secundario CID"),
    ("internacao", "CID_MORTE", "cid", "CID", "CID da morte"),
    ("internacao", "DT_INTER", "tempo", "data", "Calendario da data de internacao"),
    ("internacao_procedimento", "N_AIH", "internacao", "N_AIH", "Procedimentos vinculados a AIH/internacao"),
    ("internacao_procedimento", "PROC_REA", "procedimentos", "PROC_REA", "Procedimento realizado"),
    ("socioeconomico", "CO_MUNICIPIO_6D", "municipios", "CO_MUNICIPIO_6D", "Indicadores socioeconomicos por municipio"),
]


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def to_jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def fetch_dicts(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    result = con.execute(sql, params or [])
    columns = [d[0] for d in result.description]
    return [{c: to_jsonable(v) for c, v in zip(columns, row)} for row in result.fetchall()]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.relative_to(ROOT)} ({len(rows)} rows)")


def classify_table(schema: str, name: str) -> str:
    if schema != "main":
        return "dbt audit" if "dbt" in schema else "outro"
    if name in FACT_TABLES:
        return "fato"
    if name.startswith("stg_"):
        return "staging"
    return "dimensao/referencia"


def is_runtime_table(schema: str, name: str) -> bool:
    return schema == "main" and not name.startswith(RUNTIME_EXCLUDED_PREFIXES)


def table_inventory(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    tables = fetch_dicts(
        con,
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY table_schema, table_name
        """,
    )
    for table in tables:
        table["classificacao"] = classify_table(table["table_schema"], table["table_name"])
        table["row_count"] = con.execute(
            f"SELECT COUNT(*) FROM {quote_ident(table['table_schema'])}.{quote_ident(table['table_name'])}"
        ).fetchone()[0]
    return tables


def profile_columns(
    con: duckdb.DuckDBPyConnection,
    tables: list[dict[str, Any]],
    columns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_table: dict[str, list[dict[str, Any]]] = {}
    for col in columns:
        if col["table_schema"] == "main":
            by_table.setdefault(col["table_name"], []).append(col)

    profiles: list[dict[str, Any]] = []
    for table in tables:
        schema, name, row_count = table["table_schema"], table["table_name"], table["row_count"]
        if not is_runtime_table(schema, name) or not row_count:
            continue
        tier = "small" if row_count <= EXACT_PROFILE_MAX_ROWS else (
            "medium" if row_count <= 5_000_000 else "large"
        )
        for col in by_table.get(name, []):
            column, data_type = col["column_name"], col["data_type"]
            ref = quote_ident(column)
            exact = row_count <= EXACT_PROFILE_MAX_ROWS or (name, column) in BUSINESS_CRITICAL_FACT_COLUMNS
            distinct_expr = f"COUNT(DISTINCT {ref})" if exact else f"approx_count_distinct({ref})"
            sql = (
                f"SELECT COUNT(*) FILTER (WHERE {ref} IS NULL) AS null_count, "
                f"{distinct_expr} AS distinct_count, MIN({ref}) AS min_value, MAX({ref}) AS max_value "
                f"FROM {quote_ident(schema)}.{quote_ident(name)}"
            )
            started = time.time()
            row = fetch_dicts(con, sql)[0]
            distinct = row["distinct_count"]
            profiles.append(
                {
                    "table_schema": schema,
                    "table_name": name,
                    "column_name": column,
                    "data_type": data_type,
                    "row_count": row_count,
                    "null_count": row["null_count"],
                    "null_rate": round(row["null_count"] / row_count, 6),
                    "profile_tier": tier,
                    "profile_mode": "exact" if exact else "approx",
                    "exact_distinct_count": distinct if exact else None,
                    "approx_distinct_count": None if exact else distinct,
                    "distinct_count_for_catalog": distinct,
                    "distinct_is_exact": exact,
                    "distinct_rate": round(distinct / row_count, 6),
                    "min_value": row["min_value"],
                    "max_value": row["max_value"],
                    "profile_seconds": round(time.time() - started, 3),
                    "profile_sql": sql,
                }
            )
    return profiles


def relationship_coverage(con: duckdb.DuckDBPyConnection, table_names: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for left_table, left_key, right_table, right_key, meaning in RELATIONSHIPS:
        if left_table not in table_names or right_table not in table_names:
            print(f"skip relationship {left_table}.{left_key} -> {right_table}.{right_key}: table missing")
            continue
        lk, rk = quote_ident(left_key), quote_ident(right_key)
        sql = (
            f"SELECT COUNT(*) AS left_rows, COUNT(l.{lk}) AS non_null_left_key, "
            f"COUNT(r.{rk}) AS matched_rows, COUNT(*) - COUNT(r.{rk}) AS unmatched_rows, "
            f"COUNT(r.{rk})::DOUBLE / NULLIF(COUNT(l.{lk}), 0) AS match_rate_non_null "
            f"FROM {quote_ident(left_table)} l LEFT JOIN {quote_ident(right_table)} r "
            f"ON l.{lk} = r.{rk} WHERE l.{lk} IS NOT NULL"
        )
        started = time.time()
        result = fetch_dicts(con, sql)[0]
        rate = result["match_rate_non_null"]
        if rate is None or rate < 0.80:
            confidence, policy = "rejected", "audit_only"
        elif rate >= 0.995:
            confidence, policy = "confirmed", "business_inner_join_allowed"
        elif rate >= 0.95:
            confidence, policy = "likely", "left_join_or_explicit_mapped_scope_required"
        else:
            confidence, policy = "weak", "audit_only_unless_externally_validated"
        rows.append(
            {
                "left_table": left_table,
                "left_key": left_key,
                "right_table": right_table,
                "right_key": right_key,
                "business_meaning": meaning,
                **result,
                "confidence": confidence,
                "accepted_usage_policy": policy,
                "sql": sql,
                "duration_seconds": round(time.time() - started, 3),
            }
        )
        print(f"{left_table}.{left_key} -> {right_table}.{right_key}: {rate} ({confidence})")
    return rows


PROFILE_FIELDS = [
    "table_schema", "table_name", "column_name", "data_type", "row_count", "null_count",
    "null_rate", "profile_tier", "profile_mode", "exact_distinct_count", "approx_distinct_count",
    "distinct_count_for_catalog", "distinct_is_exact", "distinct_rate", "min_value", "max_value",
    "profile_seconds", "profile_sql",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=None, help="DuckDB file (default: CHATBOT_DB_PATH)")
    args = parser.parse_args(argv)
    db_path = (args.db or load_config(ROOT).db_path).resolve()
    if not db_path.exists():
        parser.error(f"DuckDB file not found: {db_path}")

    started = time.time()
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        inventory = table_inventory(con)
        write_csv(
            GENERATED_DIR / "table_inventory.csv",
            inventory,
            ["table_schema", "table_name", "table_type", "classificacao", "row_count"],
        )
        write_csv(
            GENERATED_DIR / "table_metadata.csv",
            fetch_dicts(
                con,
                """
                SELECT schema_name, table_name, has_primary_key, estimated_size, column_count,
                       index_count, check_constraint_count, sql
                FROM duckdb_tables() WHERE NOT internal ORDER BY schema_name, table_name
                """,
            ),
            ["schema_name", "table_name", "has_primary_key", "estimated_size", "column_count",
             "index_count", "check_constraint_count", "sql"],
        )
        columns = fetch_dicts(
            con,
            """
            SELECT table_schema, table_name, ordinal_position, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name, ordinal_position
            """,
        )
        write_csv(
            GENERATED_DIR / "column_catalog.csv",
            columns,
            ["table_schema", "table_name", "ordinal_position", "column_name", "data_type", "is_nullable"],
        )
        write_csv(
            GENERATED_DIR / "physical_constraints.csv",
            fetch_dicts(
                con,
                """
                SELECT schema_name, table_name, constraint_type, constraint_column_names,
                       constraint_name, referenced_table, referenced_column_names, constraint_text
                FROM duckdb_constraints()
                ORDER BY schema_name, table_name, constraint_type, constraint_column_names
                """,
            ),
            ["schema_name", "table_name", "constraint_type", "constraint_column_names",
             "constraint_name", "referenced_table", "referenced_column_names", "constraint_text"],
        )

        profiles = profile_columns(con, inventory, columns)
        write_csv(GENERATED_DIR / "column_profiles.csv", profiles, PROFILE_FIELDS)
        write_csv(
            GENERATED_DIR / "column_profiles_exact.csv",
            [p for p in profiles if p["distinct_is_exact"]],
            PROFILE_FIELDS,
        )
        write_csv(
            GENERATED_DIR / "column_profiles_approx.csv",
            [p for p in profiles if not p["distinct_is_exact"]],
            PROFILE_FIELDS,
        )

        main_tables = {t["table_name"] for t in inventory if t["table_schema"] == "main"}
        coverage = relationship_coverage(con, main_tables)
        write_csv(
            GENERATED_DIR / "relationship_coverage.csv",
            coverage,
            ["left_table", "left_key", "right_table", "right_key", "business_meaning", "left_rows",
             "non_null_left_key", "matched_rows", "unmatched_rows", "match_rate_non_null",
             "confidence", "accepted_usage_policy", "sql", "duration_seconds"],
        )
        write_csv(
            GENERATED_DIR / "join_policy.csv",
            [
                {
                    "left": f"{rel['left_table']}.{rel['left_key']}",
                    "right": f"{rel['right_table']}.{rel['right_key']}",
                    **rel,
                }
                for rel in coverage
            ],
            ["left", "right", "business_meaning", "left_rows", "matched_rows", "unmatched_rows",
             "match_rate_non_null", "confidence", "accepted_usage_policy"],
        )

        metadata = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "database_file": db_path.name,
            "duckdb_python_version": duckdb.__version__,
            "database_size": fetch_dicts(con, "PRAGMA database_size"),
        }
        (GENERATED_DIR / "duckdb_runtime_metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print("wrote docs/generated/duckdb_runtime_metadata.json")
    finally:
        con.close()
    print(f"done in {time.time() - started:.1f}s from {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
