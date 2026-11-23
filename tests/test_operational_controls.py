from pathlib import Path

import duckdb
import pytest

from health_system_chatbot.catalogs.duckdb_store import DuckDbCatalogStore
from health_system_chatbot.catalogs.retriever import CatalogRetriever
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.errors import CatalogBudgetExceeded, RequiredSourceUnavailable
from health_system_chatbot.models import QuestionContract, RetrievedContext, Stage1Context
from health_system_chatbot.sql_generator import _generate_sql_plan_with_pydantic_ai


def _catalog_db(path: Path) -> Path:
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE cid (CID VARCHAR, DESCRICAO VARCHAR, DS_GRUPO VARCHAR, DS_CAPITULO VARCHAR)")
        con.execute("INSERT INTO cid VALUES ('A00', 'x', 'g', 'c')")
    finally:
        con.close()
    return path


def test_catalog_duplicate_signature_is_stopped(tmp_path: Path):
    retriever = CatalogRetriever(
        store=DuckDbCatalogStore(_catalog_db(tmp_path / "c.duckdb")),
        duplicate_call_limit=1,
    )
    args = {"query": "x", "scope": "diagnosis", "limit": 5}

    retriever.guard_tool_call(tool="search_cid_catalog", args=args)
    retriever.record_tool_call(tool="search_cid_catalog", args=args)
    with pytest.raises(CatalogBudgetExceeded, match="catalog_duplicate_call"):
        retriever.guard_tool_call(tool="search_cid_catalog", args=args)
    assert retriever.tool_calls[-1].error.startswith("catalog_duplicate_call")


def test_catalog_budget_is_enforced_across_distinct_calls(tmp_path: Path):
    retriever = CatalogRetriever(
        store=DuckDbCatalogStore(_catalog_db(tmp_path / "c.duckdb")),
        tool_call_budget=2,
    )
    for value in ("a", "b"):
        args = {"query": value}
        retriever.guard_tool_call(tool="search", args=args)
        retriever.record_tool_call(tool="search", args=args)

    with pytest.raises(CatalogBudgetExceeded, match="catalog_tool_budget_exceeded"):
        retriever.guard_tool_call(tool="search", args={"query": "c"})
    assert retriever.tool_calls[-1].error.startswith("catalog_tool_budget_exceeded")


def test_missing_required_source_stops_before_agent_creation(tmp_path: Path):
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "missing.duckdb",
        openai_api_key="not-used",
    )
    context = RetrievedContext(
        question_contract=QuestionContract(required_sources=["socioeconomico"])
    )
    stage1 = Stage1Context(project_root=str(tmp_path), tables={})

    with pytest.raises(RequiredSourceUnavailable, match="socioeconomico"):
        _generate_sql_plan_with_pydantic_ai(
            "taxa por mil habitantes",
            context,
            stage1,
            config,
        )
