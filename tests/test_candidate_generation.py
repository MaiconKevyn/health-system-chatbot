from health_system_chatbot import candidate_generation as candidate_generation_module
from health_system_chatbot.candidate_generation import (
    generate_sql_candidates,
    should_use_multi_candidate,
)
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import RetrievedContext, SqlPlan, Stage1Context


def test_generate_sql_candidates_passes_variant_hints(monkeypatch, tmp_path):
    captured_hints = []

    def fake_generate_sql_plan(
        question,
        context,
        stage1_context,
        config,
        *,
        allow_llm,
        generation_hint,
    ):
        captured_hints.append(generation_hint)
        return SqlPlan(
            question=question,
            sql=f"SELECT {len(captured_hints)} AS candidate",
            source="pydantic_ai_openai",
        )

    monkeypatch.setattr(
        candidate_generation_module,
        "generate_sql_plan",
        fake_generate_sql_plan,
    )
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        enable_multi_candidate=True,
        sql_candidates=3,
    )

    plans = generate_sql_candidates(
        "Quantas internacoes existem?",
        RetrievedContext(tables=["internacoes"]),
        Stage1Context(project_root=str(tmp_path)),
        config,
    )

    assert len(plans) == 3
    assert plans[0].source == "pydantic_ai_openai:candidate_1"
    assert "principal" in captured_hints[0]
    assert "alternativa" in captured_hints[1]


def test_should_use_multi_candidate_requires_pydantic_ai_and_flag(tmp_path):
    enabled = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        enable_multi_candidate=True,
        sql_candidates=2,
    )
    disabled = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        enable_multi_candidate=False,
        sql_candidates=2,
    )

    assert should_use_multi_candidate(enabled, allow_llm=True) is True
    assert should_use_multi_candidate(disabled, allow_llm=True) is False
    assert should_use_multi_candidate(enabled, allow_llm=False) is False
