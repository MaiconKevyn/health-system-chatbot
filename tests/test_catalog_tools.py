import duckdb

from health_system_chatbot.agent_deps import ChatDeps
from health_system_chatbot.catalogs.duckdb_store import DuckDbCatalogStore
from health_system_chatbot.catalogs.retriever import CatalogRetriever
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import RetrievedContext, Stage1Context
from health_system_chatbot.tools.catalog_tools import (
    search_cid_catalog,
    search_dimension_values,
    search_procedure_catalog,
)


def _deps(tmp_path):
    db_path = tmp_path / "tools.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE cid (CID VARCHAR, DESCRICAO VARCHAR, DS_CATEGORIA VARCHAR, DS_GRUPO VARCHAR, DS_CAPITULO VARCHAR)"
        )
        con.execute(
            "INSERT INTO cid VALUES ('O80', 'Parto unico espontaneo', 'Parto unico espontaneo', 'O80-O84 Parto', 'XV. Gravidez, parto e puerperio')"
        )
        con.execute("CREATE TABLE procedimentos (PROC_REA VARCHAR, NOME_PROC VARCHAR)")
        con.execute("INSERT INTO procedimentos VALUES ('0411010034', 'PARTO CESARIANO')")
        con.execute("CREATE TABLE sexo (SEXO INTEGER, DESCRICAO VARCHAR)")
        con.execute("INSERT INTO sexo VALUES (1, 'Masculino'), (2, 'Feminino')")
    finally:
        con.close()
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=db_path,
        openai_api_key="test",
    )
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path))
    return ChatDeps(
        config=config,
        stage1_context=Stage1Context(project_root=str(tmp_path)),
        retrieved_context=RetrievedContext(),
        catalog_retriever=retriever,
    )


def test_search_cid_catalog_tool_records_call(tmp_path):
    deps = _deps(tmp_path)

    result = search_cid_catalog(deps, query="parto", scope="diagnosis")

    assert result.candidates[0].filter.value == "O80-O84 Parto"
    assert deps.catalog_retriever is not None
    assert deps.catalog_retriever.tool_calls[0].tool == "search_cid_catalog"


def test_search_procedure_catalog_tool_records_call(tmp_path):
    deps = _deps(tmp_path)

    result = search_procedure_catalog(
        deps,
        query="parto cesariano",
        scope="performed_procedure",
    )

    assert result.candidates[0].filter.value == "0411010034"
    assert deps.catalog_retriever is not None
    assert deps.catalog_retriever.tool_calls[0].tool == "search_procedure_catalog"


def test_search_dimension_values_tool_records_call(tmp_path):
    deps = _deps(tmp_path)

    result = search_dimension_values(deps, table="sexo", query="feminino")

    assert result.candidates[0].label == "Feminino"
    assert deps.catalog_retriever is not None
    assert deps.catalog_retriever.tool_calls[0].tool == "search_dimension_values"
