from health_system_chatbot import candidate_ranking as candidate_ranking_module
from health_system_chatbot.candidate_ranking import rank_sql_candidates
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import ExecutionResult, SqlPlan, Stage1Context, ValidationResult


def test_rank_sql_candidates_selects_valid_executed_candidate(monkeypatch, tmp_path):
    plans = [
        SqlPlan(question="q", sql="SELECT * FROM tabela_inexistente"),
        SqlPlan(question="q", sql="SELECT COUNT(*) AS total FROM internacoes"),
    ]
    executed_sql = []

    def fake_validate_sql(sql, ctx, *, question, plan):
        if "tabela_inexistente" in sql:
            return ValidationResult(
                is_valid=False,
                severity="error",
                errors=["Unknown table"],
            )
        return ValidationResult(
            is_valid=True,
            severity="info",
            safe_sql=sql,
        )

    def fake_execute_validated_sql(validation, *, db_path, max_rows):
        executed_sql.append(validation.safe_sql)
        return ExecutionResult(
            sql=validation.safe_sql or "",
            columns=["total"],
            rows=[{"total": 10}],
            row_count=1,
            result_hash="abc",
        )

    monkeypatch.setattr(candidate_ranking_module, "validate_sql", fake_validate_sql)
    monkeypatch.setattr(
        candidate_ranking_module,
        "execute_validated_sql",
        fake_execute_validated_sql,
    )
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
    )

    selection = rank_sql_candidates(
        plans,
        question="q",
        stage1_context=Stage1Context(project_root=str(tmp_path)),
        config=config,
    )

    assert selection.selected_candidate_id == "candidate_2"
    assert selection.selected_candidate().plan.sql == "SELECT COUNT(*) AS total FROM internacoes"
    assert executed_sql == ["SELECT COUNT(*) AS total FROM internacoes"]
    assert selection.candidates[0].execution is None
    assert selection.candidates[0].rank_reason == "invalid_sql"
