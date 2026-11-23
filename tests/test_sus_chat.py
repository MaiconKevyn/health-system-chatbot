import json
from dataclasses import replace

import duckdb
from fastapi.testclient import TestClient

from health_system_chatbot.api import ChatService, create_app
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import Stage1Context, TableContext
from health_system_chatbot.sus import engine


def test_default_chat_repairs_sql_and_serves_the_ui_contract(tmp_path, monkeypatch):
    path = tmp_path / "test.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE internacao(ano INTEGER)")
        con.execute("INSERT INTO internacao VALUES (2018), (2019), (2019)")
    config = ChatbotConfig(project_root=tmp_path, db_path=path, openai_api_key="test")
    ctx = Stage1Context(
        project_root=str(tmp_path),
        tables={
            "internacao": TableContext(
                table_name="internacao",
                columns=["ano"],
                column_types={"ano": "INTEGER"},
            )
        },
    )
    client = TestClient(
        create_app(chat_service=ChatService(config=config, stage1_context=ctx))
    )
    calls = []

    def complete(client, config, system, user, *, schema_name=None):
        calls.append(schema_name)
        if schema_name is None:
            assert "2019 | 2" in user
            return "Em 2018 houve uma internação e em 2019 houve duas."
        return json.dumps(
            {
                "answerable": True,
                "assumptions": [],
                "sql": "SELECT ausente FROM internacao"
                if schema_name == "geracao_sql"
                else "SELECT ano, COUNT(*) AS total FROM internacao GROUP BY ano ORDER BY ano",
                "chart": {
                    "kind": "linha",
                    "x": "ano",
                    "y": "total",
                    "title": "Internações por ano",
                },
            }
        )

    monkeypatch.setattr(engine, "_complete", complete)
    r = client.post(
        "/api/chat",
        json={
            "question": "Mostre um gráfico de linhas de internações por ano",
            "show_debug": True,
            "show_sql": True,
        },
    )
    r.raise_for_status()
    data = r.json()
    assert data["status"] == "answered" and data["developer_context"]["engine"] == "sus"
    assert data["sql"].startswith("SELECT ano") and data["evidence"]["row_count"] == 2
    assert data["chart"]["spec"]["data"] == [
        {"ano": 2018, "total": 1},
        {"ano": 2019, "total": 2},
    ]
    assert data["chart"]["echarts"]["series"][0]["type"] == "line"
    assert calls == ["geracao_sql", "correcao_sql", None]
    assert len(list((tmp_path / "evaluation/chatbot/traces").glob("*.json"))) == 1

    calls.clear()
    hidden = client.post(
        "/api/chat", json={"question": "Quantas internações por ano?"}
    ).json()
    assert hidden["status"] == "answered" and hidden["sql"] == ""
    assert (
        hidden["developer_context"] == {}
        and hidden["evidence"] == {}
        and hidden["chart"] is None
    )
    assert replace(config, llm_provider="ollama").active_chat_engine == "legacy"
    assert replace(config, chat_engine="legacy").active_chat_engine == "legacy"
