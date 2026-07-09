import json
from types import SimpleNamespace

import health_system_chatbot.answer_synthesizer as synth_module
from health_system_chatbot.answer_synthesizer import NaturalAnswer, synthesize_answer
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import (
    ExecutionResult,
    QuestionIntent,
    RetrievedContext,
    SqlPlan,
    ValidationResult,
    ValueHint,
)


def test_answer_keeps_metric_basis_and_caveats_out_of_user_text():
    intent = QuestionIntent(
        status="answerable",
        reason="ok",
        normalized_question="valor total",
        required_caveats=["Declarar coluna financeira."],
    )
    plan = SqlPlan(
        question="Qual e o valor total?",
        sql="SELECT SUM(VAL_TOT) AS valor_total FROM internacoes",
        metric_basis=["VAL_TOT"],
        caveats=["VAL_TOT foi usado."],
    )
    validation = ValidationResult(is_valid=True, severity="info", safe_sql=plan.sql)
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["valor_total"],
        rows=[{"valor_total": 10.0}],
        row_count=1,
        result_hash="abc",
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        show_debug=True,
    )

    assert answer.status == "answered"
    assert "VAL_TOT" not in answer.answer_pt
    assert "Declarar coluna financeira." not in answer.answer_pt
    assert "VAL_TOT foi usado." in answer.caveats
    assert "Declarar coluna financeira." in answer.caveats


def test_answer_pt_is_user_friendly_while_dev_context_keeps_artifacts():
    intent = QuestionIntent(
        status="answerable",
        reason="ok",
        normalized_question="diagnosticos porto alegre",
    )
    plan = SqlPlan(
        question="Quais diagnosticos tiveram mais mortes?",
        sql="SELECT DIAG_PRINC, DESCRICAO, total_mortes FROM ranking",
        metric_basis=["count of hospitalizations with death"],
        date_basis="internacoes.DT_INTER",
        geography_basis="residence",
        caveats=["Considera municipio de residencia."],
    )
    validation = ValidationResult(is_valid=True, severity="info", safe_sql=plan.sql)
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["DIAG_PRINC", "DESCRICAO", "total_mortes"],
        rows=[
            {"DIAG_PRINC": "A419", "DESCRICAO": "Septicemia NE", "total_mortes": 146},
            {
                "DIAG_PRINC": "P220",
                "DESCRICAO": "Sindr da angustia respirat do recem-nascido",
                "total_mortes": 205,
            },
        ],
        row_count=2,
        result_hash="abc",
    )
    context = RetrievedContext(
        tables=["internacoes", "municipios", "cid"],
        columns=["internacoes.DIAG_PRINC", "municipios.NO_MUNICIPIO", "cid.DESCRICAO"],
        retrieval_mode="schema_keyword",
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        context=context,
        related_context=[
            {
                "question": "Pergunta anterior sobre Porto Alegre",
                "answer_status": "answered",
                "result_summary": "Resumo anterior",
            }
        ],
        show_sql=True,
        show_debug=True,
    )

    assert "Sindr da angustia respirat do recem-nascido (P220): 205 mortes" in answer.answer_pt
    assert "Septicemia NE (A419): 146 mortes" in answer.answer_pt
    assert answer.answer_pt.index("P220") < answer.answer_pt.index("A419")
    assert "Primeira linha" not in answer.answer_pt
    assert answer.result_summary.startswith("A consulta retornou 2 linhas")
    assert answer.sql == plan.sql
    assert answer.developer_context["retrieved_tables"] == ["internacoes", "municipios", "cid"]
    assert answer.developer_context["related_context"][0]["question"] == (
        "Pergunta anterior sobre Porto Alegre"
    )


def test_multirow_count_summary_includes_deterministic_sum():
    intent = QuestionIntent(status="answerable", reason="ok", normalized_question="mortes por ano")
    plan = SqlPlan(question="Mortes por ano?", sql="SELECT ano, mortes FROM result")
    validation = ValidationResult(is_valid=True, severity="info", safe_sql=plan.sql)
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["ano", "mortes"],
        rows=[
            {"ano": 2020, "mortes": 68},
            {"ano": 2021, "mortes": 66},
            {"ano": 2022, "mortes": 50},
        ],
        row_count=3,
        result_hash="abc",
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        show_debug=True,
        allow_llm=False,
    )

    assert "Soma de mortes nas linhas retornadas: 184" in answer.result_summary


def test_validation_warnings_stay_out_of_user_caveats():
    intent = QuestionIntent(status="answerable", reason="ok", normalized_question="total")
    plan = SqlPlan(question="Total?", sql="SELECT COUNT(*) AS total FROM internacoes")
    validation = ValidationResult(
        is_valid=True,
        severity="warning",
        warnings=["Join requires LEFT JOIN or explicit mapped scope: internacoes.MUNIC_RES -> municipios.CO_MUNICIPIO_6D"],
        safe_sql=plan.sql,
    )
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["total"],
        rows=[{"total": 10}],
        row_count=1,
        result_hash="abc",
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        show_debug=True,
        allow_llm=False,
    )

    assert answer.caveats == []
    assert answer.developer_context["warnings"] == validation.warnings
    assert "Join requires LEFT JOIN" not in answer.answer_pt


def test_municipality_homonym_value_hints_add_user_caveat():
    intent = QuestionIntent(status="answerable", reason="ok", normalized_question="santa maria")
    plan = SqlPlan(question="Mortes em Santa Maria?", sql="SELECT COUNT(*) AS total FROM x")
    validation = ValidationResult(is_valid=True, severity="info", safe_sql=plan.sql)
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["total"],
        rows=[{"total": 10}],
        row_count=1,
        result_hash="abc",
    )
    context = RetrievedContext(
        value_hints=[
            ValueHint(
                table="municipios",
                column="NO_MUNICIPIO",
                value="Santa Maria",
                label="RS",
            ),
            ValueHint(
                table="municipios",
                column="NO_MUNICIPIO",
                value="Santa Maria",
                label="RN",
            ),
        ]
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        context=context,
        show_debug=True,
        allow_llm=False,
    )

    assert any("Santa Maria" in caveat and "RN, RS" in caveat for caveat in answer.caveats)


def test_no_debug_hides_developer_context_and_technical_payload():
    intent = QuestionIntent(status="answerable", reason="ok", normalized_question="total")
    plan = SqlPlan(question="Total?", sql="SELECT 10 AS total")
    validation = ValidationResult(is_valid=True, severity="info", safe_sql=plan.sql)
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["total"],
        rows=[{"total": 10}],
        row_count=1,
        result_hash="abc",
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        show_sql=True,
        show_debug=False,
        allow_llm=False,
    )

    assert answer.answer_pt
    assert answer.sql == plan.sql
    assert answer.result_summary == ""
    assert answer.caveats == []
    assert answer.developer_context == {}
    assert answer.evidence == {}


def test_llm_natural_answer_uses_configured_model(monkeypatch, tmp_path):
    class FakeLlm:
        def structured_predict(self, model, prompt, **kwargs):
            assert model is NaturalAnswer
            assert "Pergunta original" in getattr(prompt, "template", str(prompt))
            assert kwargs["question"] == "Total?"
            return NaturalAnswer(answer_pt="Resposta natural gerada pelo modelo.")

    captured = {}

    def fake_build_openai_llm(config):
        captured["model"] = config.llm_model
        return FakeLlm()

    monkeypatch.setattr(synth_module, "build_openai_llm", fake_build_openai_llm)
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        llm_model="gpt-test",
        agent_framework="llamaindex",
    )
    intent = QuestionIntent(status="answerable", reason="ok", normalized_question="total")
    plan = SqlPlan(
        question="Total?",
        sql="SELECT 10 AS total",
        metric_basis=["COUNT"],
        date_basis="internacoes.DT_SAIDA",
    )
    validation = ValidationResult(is_valid=True, severity="info", safe_sql=plan.sql)
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["total"],
        rows=[{"total": 10}],
        row_count=1,
        result_hash="abc",
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        config=config,
        allow_llm=True,
        show_debug=True,
    )

    assert captured["model"] == "gpt-test"
    assert answer.answer_pt == "Resposta natural gerada pelo modelo."
    assert "natural_answer_warning" not in answer.developer_context


def test_pydantic_ai_natural_answer_uses_answer_agent(monkeypatch, tmp_path):
    captured = {}

    class FakeAgent:
        def run_sync(self, prompt, *, deps):
            captured["prompt"] = prompt
            captured["deps"] = deps
            return SimpleNamespace(output=NaturalAnswer(answer_pt="Resposta via Pydantic AI."))

    monkeypatch.setattr(synth_module, "build_answer_agent", lambda config: FakeAgent())

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
    )
    intent = QuestionIntent(status="answerable", reason="ok", normalized_question="total")
    plan = SqlPlan(
        question="Total?",
        sql="SELECT 10 AS total",
        metric_basis=["COUNT"],
        date_basis="DT_INTER",
    )
    validation = ValidationResult(is_valid=True, severity="info", safe_sql=plan.sql)
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["total"],
        rows=[{"total": 10}],
        row_count=1,
        result_hash="abc",
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        config=config,
        allow_llm=True,
        show_debug=True,
    )

    assert answer.answer_pt == "Resposta via Pydantic AI."
    assert captured["deps"].config is config
    assert captured["deps"].execution is execution
    assert "Total?" in captured["prompt"]
    assert "SELECT 10 AS total" in captured["prompt"]
    assert "natural_answer_warning" not in answer.developer_context


def test_llm_answer_strips_debug_sections_from_user_text(monkeypatch, tmp_path):
    class FakeAgent:
        def run_sync(self, prompt, *, deps):
            return SimpleNamespace(
                output=NaturalAnswer(
                    answer_pt=(
                        "Foram 7.772 mortes de mulheres acima de 50 anos por infecções "
                        "em Porto Alegre (RS) ao longo dos anos analisados.\n\n"
                        "Base temporal: ano da internação, de 2007 a 2023.\n\n"
                        "Caveats: a unidade de análise é internação/AIH.\n\n"
                        "Considerei o contexto anterior relacionado."
                    )
                )
            )

    monkeypatch.setattr(synth_module, "build_answer_agent", lambda config: FakeAgent())

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
    )
    intent = QuestionIntent(status="answerable", reason="ok", normalized_question="mortes")
    plan = SqlPlan(question="Mortes?", sql="SELECT 7772 AS mortes")
    validation = ValidationResult(is_valid=True, severity="info", safe_sql=plan.sql)
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["mortes"],
        rows=[{"mortes": 7772}],
        row_count=1,
        result_hash="abc",
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        config=config,
        allow_llm=True,
        show_debug=True,
    )

    assert answer.answer_pt == (
        "Foram 7.772 mortes de mulheres acima de 50 anos por infecções "
        "em Porto Alegre (RS) ao longo dos anos analisados."
    )
    assert answer.developer_context["answer_source"] == "pydantic_ai_openai"


def test_llm_natural_answer_receives_more_than_eight_small_result_rows(monkeypatch, tmp_path):
    class FakeLlm:
        def structured_predict(self, model, prompt, **kwargs):
            rows = json.loads(kwargs["result_rows"])
            assert len(rows) == 12
            assert rows[-1] == {"ano_entrada": "2011", "total_internacoes": 110}
            return NaturalAnswer(answer_pt="Resposta com todos os anos.")

    monkeypatch.setattr(synth_module, "build_openai_llm", lambda config: FakeLlm())

    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="llamaindex",
    )
    intent = QuestionIntent(status="answerable", reason="ok", normalized_question="por ano")
    plan = SqlPlan(
        question="Quantas internacoes ocorreram por ano de entrada?",
        sql="SELECT ano_entrada, total_internacoes FROM result",
        metric_basis=["COUNT"],
        date_basis="DT_INTER",
    )
    validation = ValidationResult(is_valid=True, severity="info", safe_sql=plan.sql)
    execution = ExecutionResult(
        sql=plan.sql,
        columns=["ano_entrada", "total_internacoes"],
        rows=[
            {"ano_entrada": str(2000 + idx), "total_internacoes": idx * 10}
            for idx in range(12)
        ],
        row_count=12,
        result_hash="abc",
    )

    answer = synthesize_answer(
        question=plan.question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        config=config,
        allow_llm=True,
    )

    assert answer.answer_pt == "Resposta com todos os anos."
