from pathlib import Path

import duckdb
import pytest

from health_system_chatbot.duckdb_executor import execute_validated_sql
from health_system_chatbot.models import ValidationResult


def test_executor_runs_validated_sql_read_only(tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE numbers (value INTEGER)")
    con.execute("INSERT INTO numbers VALUES (1), (2)")
    con.close()

    validation = ValidationResult(
        is_valid=True,
        severity="info",
        safe_sql="SELECT COUNT(*) AS total FROM numbers",
    )
    result = execute_validated_sql(validation, db_path=db_path)

    assert result.rows == [{"total": 2}]
    assert result.result_hash
    assert result.elapsed_seconds >= 0


def test_executor_rejects_unvalidated_sql(tmp_path: Path):
    validation = ValidationResult(is_valid=False, severity="error", errors=["bad"])

    with pytest.raises(ValueError):
        execute_validated_sql(validation, db_path=tmp_path / "missing.duckdb")



def test_executor_cancels_sql_that_exceeds_the_timeout(tmp_path: Path):
    import time

    from health_system_chatbot.duckdb_executor import SqlTimeoutError

    db_path = tmp_path / "test.duckdb"
    duckdb.connect(str(db_path)).close()
    validation = ValidationResult(
        is_valid=True,
        severity="info",
        safe_sql="SELECT SUM(i) AS total FROM range(100000000000) t(i)",
    )

    started = time.perf_counter()
    with pytest.raises(SqlTimeoutError, match="0.3s limit"):
        execute_validated_sql(validation, db_path=db_path, timeout_seconds=0.3)

    assert time.perf_counter() - started < 5


def test_executor_timeout_does_not_affect_fast_queries(tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    duckdb.connect(str(db_path)).close()
    validation = ValidationResult(is_valid=True, severity="info", safe_sql="SELECT 1 AS one")

    result = execute_validated_sql(validation, db_path=db_path, timeout_seconds=5)

    assert result.rows == [{"one": 1}]
