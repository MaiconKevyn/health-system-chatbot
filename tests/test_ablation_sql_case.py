import duckdb

from evaluation.chatbot.eval_core.sql_case import evaluate_generated_sql
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import GroundTruthItem, Stage1Context, TableContext


def _context(tmp_path):
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE internacoes (id INTEGER, MORTE BOOLEAN)")
        con.execute("INSERT INTO internacoes VALUES (1, true), (2, false)")
    finally:
        con.close()

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=db_path,
        openai_api_key=None,
    )
    stage1_context = Stage1Context(
        project_root=str(tmp_path),
        tables={
            "internacoes": TableContext(
                table_name="internacoes",
                columns=["id", "MORTE"],
                column_types={"id": "INTEGER", "MORTE": "BOOLEAN"},
            )
        },
    )
    item = GroundTruthItem(
        id="T001",
        question_pt="Quantas internacoes existem?",
        sql="SELECT COUNT(*) AS total FROM internacoes",
        expected_result_type="scalar",
    )
    return config, stage1_context, item


def test_evaluate_generated_sql_compares_executed_results(tmp_path):
    config, stage1_context, item = _context(tmp_path)

    record = evaluate_generated_sql(
        item,
        variant="test",
        strategy="fake",
        generated_sql="SELECT COUNT(*) AS total FROM internacoes",
        config=config,
        ctx=stage1_context,
        retrieved=None,
        max_rows=100,
        timeout_seconds=5,
        numeric_tolerance=1e-6,
    )

    assert record["generated_sql_valid"] is True
    assert record["generated_execution_status"] == "passed"
    assert record["result_match"] is True


def test_evaluate_generated_sql_blocks_unsafe_sql(tmp_path):
    config, stage1_context, item = _context(tmp_path)

    record = evaluate_generated_sql(
        item,
        variant="test",
        strategy="fake",
        generated_sql="DROP TABLE internacoes",
        config=config,
        ctx=stage1_context,
        retrieved=None,
        max_rows=100,
        timeout_seconds=5,
        numeric_tolerance=1e-6,
    )

    assert record["generated_sql_valid"] is False
    assert record["generated_execution_status"] == "skipped"
    assert record["error_category"] == "unsafe_sql_blocked"


def test_evaluate_generated_sql_falls_back_to_duckdb_for_cte_column_resolution(tmp_path):
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE internacoes (PROC_REA VARCHAR)")
        con.execute("CREATE TABLE procedimentos (PROC_REA VARCHAR, NOME_PROC VARCHAR)")
        con.execute("INSERT INTO internacoes VALUES ('A'), ('A'), ('B')")
        con.execute("INSERT INTO procedimentos VALUES ('A', 'Proc A'), ('B', 'Proc B')")
    finally:
        con.close()

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=db_path,
        openai_api_key=None,
    )
    stage1_context = Stage1Context(
        project_root=str(tmp_path),
        tables={
            "internacoes": TableContext(
                table_name="internacoes",
                columns=["PROC_REA"],
                column_types={"PROC_REA": "VARCHAR"},
            ),
            "procedimentos": TableContext(
                table_name="procedimentos",
                columns=["PROC_REA", "NOME_PROC"],
                column_types={"PROC_REA": "VARCHAR", "NOME_PROC": "VARCHAR"},
            ),
        },
    )
    item = GroundTruthItem(
        id="T002",
        question_pt="Quais procedimentos principais aparecem?",
        sql=(
            'WITH base AS (SELECT p."PROC_REA", p."NOME_PROC", COUNT(*) AS total '
            'FROM internacoes i JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'GROUP BY p."PROC_REA", p."NOME_PROC") '
            'SELECT "PROC_REA", "NOME_PROC", total FROM base ORDER BY total DESC'
        ),
        expected_result_type="ranking",
    )

    record = evaluate_generated_sql(
        item,
        variant="test",
        strategy="fake",
        generated_sql=(
            "WITH base AS (SELECT i.PROC_REA, p.NOME_PROC, COUNT(*) AS total "
            "FROM internacoes i JOIN procedimentos p ON i.PROC_REA = p.PROC_REA "
            "GROUP BY i.PROC_REA, p.NOME_PROC) "
            "SELECT PROC_REA, NOME_PROC, total FROM base ORDER BY total DESC"
        ),
        config=config,
        ctx=stage1_context,
        retrieved=None,
        max_rows=100,
        timeout_seconds=5,
        numeric_tolerance=1e-6,
    )

    assert record["generated_sql_valid"] is True
    assert record["generated_execution_status"] == "passed"
    assert record["result_match"] is True
    assert any("Static validation was overridden" in warning for warning in record["generated_sql_validation_warnings"])
