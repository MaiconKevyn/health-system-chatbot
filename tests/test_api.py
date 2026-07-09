from fastapi.testclient import TestClient

from health_system_chatbot.api import ChatService, create_app
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import ChatbotAnswer, Stage1Context


class FakeChatService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ask(
        self,
        question: str,
        *,
        show_sql: bool,
        allow_llm: bool,
        show_debug: bool,
    ) -> ChatbotAnswer:
        self.calls.append(
            {
                "question": question,
                "show_sql": show_sql,
                "allow_llm": allow_llm,
                "show_debug": show_debug,
            }
        )
        return ChatbotAnswer(
            answer_pt="Resposta: total=10",
            sql="SELECT 10 AS total",
            result_summary="total=10",
            caveats=["Usa dados locais."],
            evidence={"row_count": 1},
            developer_context={"technical_summary": "total=10"},
            status="answered",
        )


def test_chat_endpoint_delegates_question_to_chat_service():
    service = FakeChatService()
    client = TestClient(create_app(chat_service=service))

    response = client.post(
        "/api/chat",
        json={
            "question": "Quantas internacoes existem?",
            "show_sql": True,
            "allow_llm": False,
            "show_debug": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer_pt": "Resposta: total=10",
        "sql": "SELECT 10 AS total",
        "result_summary": "total=10",
        "caveats": ["Usa dados locais."],
        "evidence": {"row_count": 1},
        "developer_context": {"technical_summary": "total=10"},
        "chart": None,
        "status": "answered",
    }
    assert service.calls == [
        {
            "question": "Quantas internacoes existem?",
            "show_sql": True,
            "allow_llm": False,
            "show_debug": True,
        }
    ]


def test_chat_endpoint_defaults_show_debug_to_false():
    service = FakeChatService()
    client = TestClient(create_app(chat_service=service))

    response = client.post(
        "/api/chat",
        json={
            "question": "Quantas internacoes existem?",
        },
    )

    assert response.status_code == 200
    assert service.calls == [
        {
            "question": "Quantas internacoes existem?",
            "show_sql": False,
            "allow_llm": True,
            "show_debug": False,
        }
    ]


def test_chat_endpoint_rejects_blank_question():
    service = FakeChatService()
    client = TestClient(create_app(chat_service=service))

    response = client.post("/api/chat", json={"question": "   "})

    assert response.status_code == 422
    assert service.calls == []


def test_react_frontend_build_is_served_from_root(tmp_path):
    dist = tmp_path / "frontend/dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div>'
        '<script type="module" src="/assets/index-test.js"></script></body></html>',
        encoding="utf-8",
    )
    (assets / "index-test.js").write_text("console.log('react build')", encoding="utf-8")
    service = ChatService(
        config=ChatbotConfig(
            project_root=tmp_path,
            db_path=tmp_path / "test.duckdb",
            openai_api_key="test",
        ),
        stage1_context=Stage1Context(project_root=str(tmp_path)),
    )
    client = TestClient(create_app(chat_service=service))

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="root"' in response.text
    assert "/assets/index-test.js" in response.text
    asset_response = client.get("/assets/index-test.js")
    assert asset_response.status_code == 200
    assert "react build" in asset_response.text


def test_legacy_frontend_still_exists_as_fallback():
    client = TestClient(create_app(chat_service=FakeChatService()))

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="root"' in response.text or 'id="chat-form"' in response.text
