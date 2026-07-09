from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .normalization import expand_query_terms, normalize_catalog_text, normalize_code


CID_COLUMNS = ("CID", "DESCRICAO", "DS_CATEGORIA", "DS_GRUPO", "DS_CAPITULO")
PROCEDURE_COLUMNS = ("PROC_REA", "NOME_PROC")


class CatalogUnavailableError(RuntimeError):
    pass


class DuckDbCatalogStore:
    def __init__(self, db_path: Path, *, synonyms: dict[str, list[str]] | None = None) -> None:
        self.db_path = db_path
        self.synonyms = synonyms or {}

    def search_cid_rows(self, query: str, *, limit: int = 100) -> list[dict[str, Any]]:
        terms = expand_query_terms(query, self.synonyms)
        if not terms:
            return []
        rows = []
        for row in _fetch_cid_rows(str(self.db_path)):
            if _row_matches(row, CID_COLUMNS, terms):
                rows.append(_row_dict(CID_COLUMNS, row))
        return rows if limit <= 0 else rows[:limit]

    def search_procedure_rows(self, query: str, *, limit: int = 100) -> list[dict[str, Any]]:
        terms = expand_query_terms(query, self.synonyms)
        if not terms:
            return []
        rows = []
        for row in _fetch_procedure_rows(str(self.db_path)):
            if _row_matches(row, PROCEDURE_COLUMNS, terms):
                rows.append(_row_dict(PROCEDURE_COLUMNS, row))
        return rows if limit <= 0 else rows[:limit]

    def search_dimension_rows(
        self,
        *,
        table: str,
        columns: tuple[str, ...],
        query: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        terms = expand_query_terms(query, self.synonyms)
        if not terms:
            return []
        rows = []
        for row in _fetch_table_rows(str(self.db_path), table, columns):
            if _row_matches(row, columns, terms):
                rows.append(_row_dict(columns, row))
        return rows if limit <= 0 else rows[:limit]


def _row_dict(columns: tuple[str, ...], row: tuple[Any, ...]) -> dict[str, Any]:
    return {column: row[index] for index, column in enumerate(columns)}


def _row_matches(row: tuple[Any, ...], columns: tuple[str, ...], terms: list[str]) -> bool:
    values = {column: str(row[index] or "") for index, column in enumerate(columns)}
    normalized_values = [normalize_catalog_text(value) for value in values.values()]
    cid_or_code = normalize_code(values.get("CID") or values.get("PROC_REA") or "")
    for term in terms:
        normalized_term = normalize_catalog_text(term)
        if not normalized_term:
            continue
        if cid_or_code and normalize_code(normalized_term) == cid_or_code:
            return True
        if any(_term_matches_text(normalized_term, value) for value in normalized_values):
            return True
    return False


def _term_matches_text(term: str, text: str) -> bool:
    if term in text:
        return True
    if len(term) >= 6 and term[:6] in text:
        return True
    return False


def _quote_identifier(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier}")
    return f'"{identifier}"'


@lru_cache(maxsize=8)
def _fetch_cid_rows(db_path: str) -> tuple[tuple[Any, ...], ...]:
    return _fetch_table_rows(db_path, "cid", CID_COLUMNS)


@lru_cache(maxsize=8)
def _fetch_procedure_rows(db_path: str) -> tuple[tuple[Any, ...], ...]:
    return _fetch_table_rows(db_path, "procedimentos", PROCEDURE_COLUMNS)


@lru_cache(maxsize=128)
def _fetch_table_rows(
    db_path: str,
    table: str,
    columns: tuple[str, ...],
) -> tuple[tuple[Any, ...], ...]:
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    try:
        table_exists = con.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = ?
            """,
            [table],
        ).fetchone()[0]
        if not table_exists:
            raise CatalogUnavailableError(f"Catalog table not found: {table}")

        available_columns = {
            row[0]
            for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [table],
            ).fetchall()
        }
        missing = [column for column in columns if column not in available_columns]
        if missing:
            raise CatalogUnavailableError(
                f"Catalog table {table} is missing columns: {', '.join(missing)}"
            )

        column_sql = ", ".join(_quote_identifier(column) for column in columns)
        return tuple(
            con.execute(
                f"SELECT {column_sql} FROM {_quote_identifier(table)}"
            ).fetchall()
        )
    finally:
        con.close()
