import health_system_chatbot.workflow as workflow_module
from health_system_chatbot.candidate_ranking import RankedSqlCandidate, SqlCandidateSelection
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import (
    ChatbotAnswer,
    ExecutionResult,
    RetrievedContext,
    SqlPlan,
    Stage1Context,
    TableContext,
    ValidationResult,
)
from health_system_chatbot.workflow import run_chat


def test_run_chat_corrects_invalid_sql_before_execution(monkeypatch, tmp_path):
    generated_plan = SqlPlan(
        question="Quantas internacoes existem?",
        sql="SELECT COUNT(*) AS total_internacoes FROM tabela_inexistente",
    )
    corrected_plan = SqlPlan(
        question="Quantas internacoes existem?",
        sql="SELECT COUNT(*) AS total_internacoes FROM internacoes",
        source="pydantic_ai_refiner",
    )
    executed_sql = {}

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
        "refine_sql_plan",
        lambda **kwargs: corrected_plan,
    )

    def fake_execute(validation, *, db_path, max_rows):
        executed_sql["sql"] = validation.safe_sql
        return ExecutionResult(
            sql=validation.safe_sql or "",
            columns=["total_internacoes"],
            rows=[{"total_internacoes": 10}],
            row_count=1,
            result_hash="abc",
        )

    monkeypatch.setattr(workflow_module, "execute_validated_sql", fake_execute)
    monkeypatch.setattr(
        workflow_module,
        "synthesize_answer",
        lambda **kwargs: ChatbotAnswer(answer_pt="ok", status="answered"),
    )

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
        sql_correction_attempts=2,
    )
    ctx = Stage1Context(
        project_root=str(tmp_path),
        tables={"internacoes": TableContext(table_name="internacoes")},
    )

    answer = run_chat(
        "Quantas internacoes existem?",
        config=config,
        stage1_context=ctx,
        write_trace=False,
        write_audit_log=False,
    )

    assert answer.status == "answered"
    assert executed_sql["sql"] == "SELECT COUNT(*) AS total_internacoes FROM internacoes"


def test_run_chat_refines_after_execution_error(monkeypatch, tmp_path):
    generated_plan = SqlPlan(
        question="Quantas internacoes existem?",
        sql="SELECT COUNT(*) AS total_internacoes FROM internacoes",
    )
    corrected_plan = SqlPlan(
        question="Quantas internacoes existem?",
        sql="SELECT COUNT(*) AS total_internacoes FROM internacoes",
        source="pydantic_ai_refiner",
    )
    execute_calls = []
    captured_refine_kwargs = {}

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

    def fake_refine_sql_plan(**kwargs):
        captured_refine_kwargs.update(kwargs)
        return corrected_plan

    monkeypatch.setattr(workflow_module, "refine_sql_plan", fake_refine_sql_plan)

    def fake_execute(validation, *, db_path, max_rows):
        execute_calls.append(validation.safe_sql)
        if len(execute_calls) == 1:
            raise RuntimeError("DuckDB binder error")
        return ExecutionResult(
            sql=validation.safe_sql or "",
            columns=["total_internacoes"],
            rows=[{"total_internacoes": 10}],
            row_count=1,
            result_hash="abc",
        )

    monkeypatch.setattr(workflow_module, "execute_validated_sql", fake_execute)
    monkeypatch.setattr(
        workflow_module,
        "synthesize_answer",
        lambda **kwargs: ChatbotAnswer(answer_pt="ok", status="answered"),
    )

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
        sql_correction_attempts=2,
    )
    ctx = Stage1Context(
        project_root=str(tmp_path),
        tables={"internacoes": TableContext(table_name="internacoes")},
    )

    answer = run_chat(
        "Quantas internacoes existem?",
        config=config,
        stage1_context=ctx,
        write_trace=False,
        write_audit_log=False,
    )

    assert answer.status == "answered"
    assert execute_calls == [
        "SELECT COUNT(*) AS total_internacoes FROM internacoes",
        "SELECT COUNT(*) AS total_internacoes FROM internacoes",
    ]
    assert captured_refine_kwargs["validation_errors"] == []
    assert captured_refine_kwargs["execution_error"] == "DuckDB binder error"


def test_run_chat_uses_ranked_multi_candidate_execution(monkeypatch, tmp_path):
    first_plan = SqlPlan(
        question="Quantas internacoes existem?",
        sql="SELECT COUNT(*) AS total FROM tabela_inexistente",
        source="pydantic_ai_openai:candidate_1",
    )
    selected_plan = SqlPlan(
        question="Quantas internacoes existem?",
        sql="SELECT COUNT(*) AS total FROM internacoes",
        source="pydantic_ai_openai:candidate_2",
    )
    validation = ValidationResult(
        is_valid=True,
        severity="info",
        safe_sql=selected_plan.sql,
    )
    execution = ExecutionResult(
        sql=selected_plan.sql,
        columns=["total"],
        rows=[{"total": 10}],
        row_count=1,
        result_hash="abc",
    )
    captured = {}

    monkeypatch.setattr(
        workflow_module,
        "retrieve_context",
        lambda question, stage1_context, config: RetrievedContext(tables=["internacoes"]),
    )
    monkeypatch.setattr(
        workflow_module,
        "generate_sql_candidates",
        lambda question, context, stage1_context, config, allow_llm: [first_plan, selected_plan],
    )
    monkeypatch.setattr(
        workflow_module,
        "rank_sql_candidates",
        lambda candidates, question, stage1_context, config: SqlCandidateSelection(
            selected_candidate_id="candidate_2",
            candidates=[
                RankedSqlCandidate(
                    candidate_id="candidate_1",
                    plan=first_plan,
                    validation=ValidationResult(
                        is_valid=False,
                        severity="error",
                        errors=["Unknown table"],
                    ),
                    score=-100,
                    rank_reason="invalid_sql",
                    errors=["Unknown table"],
                ),
                RankedSqlCandidate(
                    candidate_id="candidate_2",
                    plan=selected_plan,
                    validation=validation,
                    execution=execution,
                    score=110,
                    rank_reason="validated_and_executed",
                ),
            ],
            selection_reason="Selected candidate_2",
        ),
    )
    monkeypatch.setattr(
        workflow_module,
        "execute_validated_sql",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should reuse execution")),
    )

    def fake_synthesize_answer(**kwargs):
        captured.update(kwargs)
        return ChatbotAnswer(answer_pt="ok", status="answered")

    monkeypatch.setattr(workflow_module, "synthesize_answer", fake_synthesize_answer)

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
        enable_multi_candidate=True,
        sql_candidates=2,
    )
    ctx = Stage1Context(
        project_root=str(tmp_path),
        tables={"internacoes": TableContext(table_name="internacoes")},
    )

    answer = run_chat(
        "Quantas internacoes existem?",
        config=config,
        stage1_context=ctx,
        write_trace=False,
        write_audit_log=False,
    )

    assert answer.status == "answered"
    assert captured["plan"] is selected_plan
    assert captured["execution"] is execution
