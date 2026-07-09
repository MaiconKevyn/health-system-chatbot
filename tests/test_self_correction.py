from types import SimpleNamespace

import health_system_chatbot.self_correction as correction_module
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import RetrievedContext, SqlPlan, Stage1Context
from health_system_chatbot.self_correction import refine_sql_plan


def test_refine_sql_plan_uses_pydantic_ai_refiner(monkeypatch, tmp_path):
    captured = {}

    class FakeAgent:
        def run_sync(self, prompt, *, deps):
            captured["prompt"] = prompt
            captured["deps"] = deps
            return SimpleNamespace(
                output=SqlPlan(
                    question="Quantas internacoes existem?",
                    sql="SELECT COUNT(*) AS total_internacoes FROM internacoes",
                )
            )

    monkeypatch.setattr(
        correction_module,
        "build_sql_refiner_agent",
        lambda config: FakeAgent(),
    )
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
    )
    rejected = SqlPlan(
        question="Quantas internacoes existem?",
        sql="SELECT COUNT(*) FROM tabela_inexistente",
    )

    plan = refine_sql_plan(
        question="Quantas internacoes existem?",
        context=RetrievedContext(tables=["internacoes"], table_context=["table=internacoes"]),
        stage1_context=Stage1Context(project_root=str(tmp_path)),
        rejected_plan=rejected,
        validation_errors=["Unknown or unsupported table(s): tabela_inexistente"],
        execution_error=None,
        config=config,
    )

    assert plan.source == "pydantic_ai_refiner"
    assert plan.metric_basis == ["COUNT"]
    assert "tabela_inexistente" in captured["prompt"]
    assert captured["deps"].rejected_plan is rejected
    assert captured["deps"].validation_errors == [
        "Unknown or unsupported table(s): tabela_inexistente"
    ]

