import duckdb
from fastapi.testclient import TestClient

from health_system_chatbot.api import ChatService, create_app
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import Stage1Context, TableContext


def _client_with_duckdb(tmp_path) -> TestClient:
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE internacoes (
                id INTEGER,
                SEXO INTEGER,
                MORTE BOOLEAN
            )
            """
        )
        con.execute("INSERT INTO internacoes VALUES (1, 1, false), (2, 2, true)")
    finally:
        con.close()

    service = ChatService(
        config=ChatbotConfig(
            project_root=tmp_path,
            db_path=db_path,
            openai_api_key="test",
            llm_model="gpt-5.4-mini",
        ),
        stage1_context=Stage1Context(
            project_root=str(tmp_path),
            tables={
                "internacoes": TableContext(
                    table_name="internacoes",
                    estimated_size=2,
                    columns=["id", "SEXO", "MORTE"],
                    column_types={
                        "id": "INTEGER",
                        "SEXO": "INTEGER",
                        "MORTE": "BOOLEAN",
                    },
                )
            },
        ),
    )
    return TestClient(create_app(chat_service=service))


def test_schema_endpoint_returns_tables_and_selected_table_context(tmp_path):
    client = _client_with_duckdb(tmp_path)

    response = client.get("/api/schema?table=internacoes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_table"] == "internacoes"
    assert payload["tables"] == ["internacoes"]
    assert "## internacoes" in payload["schema"]
    assert "`MORTE`: BOOLEAN" in payload["schema"]


def test_models_and_health_endpoints_match_frontend_contract(tmp_path):
    client = _client_with_duckdb(tmp_path)

    health = client.get("/api/agent-health").json()
    models = client.get("/api/models").json()

    assert health["agent_status"] == "online"
    assert models["current_model"]["model_name"] == "gpt-5.4-mini"
    assert models["current_model"]["agent_framework"] == "pydantic_ai"


def test_database_explorer_endpoints_query_duckdb_read_only(tmp_path):
    client = _client_with_duckdb(tmp_path)

    overview = client.get("/api/database/overview")
    table = client.get("/api/database/table/main/internacoes?limit=1")
    query = client.post(
        "/api/database/query",
        json={"sql": "SELECT COUNT(*) AS total FROM internacoes", "limit": 10},
    )

    assert overview.status_code == 200
    assert overview.json()["tables"][0]["table_name"] == "internacoes"
    assert table.status_code == 200
    assert table.json()["sample_columns"] == ["id", "SEXO", "MORTE"]
    assert table.json()["sample_rows"] == [{"id": 1, "SEXO": 1, "MORTE": False}]
    assert query.status_code == 200
    assert query.json()["rows"] == [{"total": 2}]


def test_database_query_blocks_mutating_sql(tmp_path):
    client = _client_with_duckdb(tmp_path)

    response = client.post(
        "/api/database/query",
        json={"sql": "DROP TABLE internacoes", "limit": 10},
    )

    assert response.status_code == 400
    assert "Blocked SQL keyword: DROP" in response.json()["detail"]
