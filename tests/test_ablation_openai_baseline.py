import pytest

from evaluation.chatbot.ablation.baseline_openai import (
    build_baseline_prompt,
    build_retry_prompt,
    extract_sql_from_text,
)
from health_system_chatbot.models import RetrievedContext, Stage1Context


def test_extract_sql_from_plain_or_fenced_response():
    assert extract_sql_from_text("SELECT COUNT(*) FROM internacoes;") == (
        "SELECT COUNT(*) FROM internacoes;"
    )
    assert extract_sql_from_text("```sql\nSELECT 1 AS total\n```") == "SELECT 1 AS total"


def test_extract_sql_rejects_response_without_sql():
    with pytest.raises(ValueError, match="SELECT or WITH"):
        extract_sql_from_text("Nao sei responder.")


def test_baseline_prompt_includes_rules_schema_and_question():
    retrieved = RetrievedContext(
        tables=["internacoes"],
        columns=["internacoes.MORTE"],
        table_context=["table=internacoes\ncolumns=MORTE"],
    )

    prompt = build_baseline_prompt(
        question="Quantas mortes existem?",
        retrieved=retrieved,
        stage1_context=Stage1Context(project_root="/tmp"),
        mode="retrieved_schema",
    )

    assert "Use somente SELECT ou WITH" in prompt
    assert "internacoes.MORTE" in prompt
    assert "Quantas mortes existem?" in prompt


def test_retry_prompt_preserves_error_feedback():
    prompt = build_retry_prompt(
        original_prompt="base prompt",
        previous_sql="SELECT missing FROM internacoes",
        error_message="Unknown column",
    )

    assert "SQL anterior" in prompt
    assert "Unknown column" in prompt
    assert "Retorne apenas uma nova query" in prompt
