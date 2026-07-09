import health_system_chatbot.workflow as workflow_module
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import (
    ExecutionResult,
    RetrievedContext,
    SqlPlan,
    Stage1Context,
    TableContext,
)
from health_system_chatbot.workflow import run_chat


def test_run_chat_returns_chart_payload_when_user_requests_graph(monkeypatch, tmp_path):
    generated_plan = SqlPlan(
        question="mortes por ano",
        sql="SELECT 2021 AS ano, 10 AS mortes",
    )

    monkeypatch.setattr(
        workflow_module,
        "retrieve_context",
        lambda question, stage1_context, config: RetrievedContext(tables=["internacoes"]),
    )
    monkeypatch.setattr(
        workflow_module,
        "generate_sql_plan",
        lambda question, context, stage1_context, config, allow_llm, chart_plan: generated_plan,
    )
    monkeypatch.setattr(
        workflow_module,
        "execute_validated_sql",
        lambda validation, *, db_path, max_rows: ExecutionResult(
            sql=validation.safe_sql or "",
            columns=["ano", "mortes"],
            rows=[{"ano": 2021, "mortes": 10}, {"ano": 2022, "mortes": 12}],
            row_count=2,
            result_hash="abc",
        ),
    )

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
        sql_correction_attempts=0,
    )
    ctx = Stage1Context(
        project_root=str(tmp_path),
        tables={"internacoes": TableContext(table_name="internacoes")},
    )

    answer = run_chat(
        "Gere um grafico de mortes por ano",
        config=config,
        stage1_context=ctx,
        allow_llm=False,
        write_trace=False,
        write_audit_log=False,
    )

    assert answer.status == "answered"
    assert answer.chart is not None
    assert answer.chart.spec is not None
    assert answer.chart.spec.chart_type == "line"
    assert answer.chart.echarts is not None


def test_run_chat_does_not_return_chart_payload_for_normal_question(monkeypatch, tmp_path):
    generated_plan = SqlPlan(
        question="quantas internacoes existem",
        sql="SELECT 10 AS internacoes",
    )

    monkeypatch.setattr(
        workflow_module,
        "retrieve_context",
        lambda question, stage1_context, config: RetrievedContext(tables=["internacoes"]),
    )
    monkeypatch.setattr(
        workflow_module,
        "generate_sql_plan",
        lambda question, context, stage1_context, config, allow_llm: generated_plan,
    )
    monkeypatch.setattr(
        workflow_module,
        "execute_validated_sql",
        lambda validation, *, db_path, max_rows: ExecutionResult(
            sql=validation.safe_sql or "",
            columns=["internacoes"],
            rows=[{"internacoes": 10}],
            row_count=1,
            result_hash="abc",
        ),
    )

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
    )
    ctx = Stage1Context(
        project_root=str(tmp_path),
        tables={"internacoes": TableContext(table_name="internacoes")},
    )

    answer = run_chat(
        "Quantas internacoes existem?",
        config=config,
        stage1_context=ctx,
        allow_llm=False,
        write_trace=False,
        write_audit_log=False,
    )

    assert answer.status == "answered"
    assert answer.chart is None
