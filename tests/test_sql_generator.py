from pathlib import Path
from types import SimpleNamespace

import health_system_chatbot.sql_generator as sql_generator_module
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import (
    BusinessMetric,
    GroundTruthItem,
    RetrievedContext,
    SqlPlan,
    Stage1Context,
    ValueHint,
)
from health_system_chatbot.sql_generator import generate_sql_plan


def test_generate_sql_plan_uses_pydantic_ai_agent(monkeypatch, tmp_path):
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
        sql_generator_module,
        "build_sql_plan_agent",
        lambda config: FakeAgent(),
    )
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
    )
    context = RetrievedContext(
        tables=["internacoes"],
        columns=["internacoes.DT_INTER"],
        table_context=["table=internacoes\ncolumns=DT_INTER"],
        business_metrics=[
            BusinessMetric(
                name="total_internacoes",
                description="Contagem de internacoes.",
                formula="COUNT(*) FROM internacoes",
            )
        ],
        value_hints=[
            ValueHint(
                table="municipios",
                column="NO_MUNICIPIO",
                value="Porto Alegre",
                label="RS",
                match_reason="test",
            )
        ],
        query_examples=[
            GroundTruthItem(
                id="QTEST",
                question_pt="Quantas internacoes existem?",
                sql="SELECT COUNT(*) FROM internacoes",
            )
        ],
        retrieval_mode="test",
    )
    stage1_context = Stage1Context(project_root=str(tmp_path))

    plan = generate_sql_plan(
        "Quantas internacoes existem?",
        context,
        stage1_context,
        config,
    )

    assert plan.source == "pydantic_ai_openai"
    assert plan.metric_basis == ["COUNT"]
    assert plan.grain == "hospitalization"
    assert captured["deps"].config is config
    assert captured["deps"].retrieved_context is context
    assert "Quantas internacoes existem?" in captured["prompt"]
    assert "table=internacoes" in captured["prompt"]
    assert "total_internacoes" in captured["prompt"]
    assert "municipios.NO_MUNICIPIO=Porto Alegre" in captured["prompt"]
    assert "QTEST" in captured["prompt"]
    assert "EXEMPLO_EXATO" in captured["prompt"]


def test_generate_sql_plan_can_still_route_to_llamaindex(monkeypatch, tmp_path):
    class FakeLlm:
        def structured_predict(self, model, prompt, **kwargs):
            assert model is SqlPlan
            assert "context" in kwargs
            return SqlPlan(
                question=kwargs["question"],
                sql="SELECT SUM(VAL_TOT) AS valor_total FROM internacoes",
            )

    import health_system_chatbot.llm as llm_module

    monkeypatch.setattr(llm_module, "build_openai_llm", lambda config: FakeLlm())
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="llamaindex",
    )

    plan = generate_sql_plan(
        "Qual e o valor total aprovado?",
        RetrievedContext(tables=["internacoes"]),
        Stage1Context(project_root=str(tmp_path)),
        config,
    )

    assert plan.source == "llamaindex_openai"
    assert plan.metric_basis == ["VAL_TOT"]


def test_prompt_includes_schema_linking_and_shape_guidance(monkeypatch, tmp_path):
    captured = {}

    class FakeAgent:
        def run_sync(self, prompt, *, deps):
            captured["prompt"] = prompt
            return SimpleNamespace(
                output=SqlPlan(
                    question="Como as internacoes se distribuem por carater de internacao?",
                    sql=(
                        "SELECT c.DESCRICAO AS carater, COUNT(*) AS internacoes "
                        "FROM internacoes i JOIN car_int c ON i.CAR_INT = c.CAR_INT "
                        "GROUP BY 1 ORDER BY internacoes DESC"
                    ),
                )
            )

    monkeypatch.setattr(
        sql_generator_module,
        "build_sql_plan_agent",
        lambda config: FakeAgent(),
    )
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
    )
    context = RetrievedContext(
        tables=["internacoes", "car_int"],
        columns=["internacoes.CAR_INT", "car_int.CAR_INT", "car_int.DESCRICAO"],
        table_context=[
            "table=internacoes\ncolumns=CAR_INT",
            "table=car_int\ncolumns=CAR_INT, DESCRICAO",
        ],
        retrieval_mode="test",
    )

    generate_sql_plan(
        "Como as internacoes se distribuem por carater de internacao?",
        context,
        Stage1Context(project_root=str(tmp_path)),
        config,
    )

    assert "Orientacoes aplicaveis para geracao SQL" in captured["prompt"]
    assert "internacoes.CAR_INT -> car_int.CAR_INT" in captured["prompt"]
    assert "retorne car_int.DESCRICAO" in captured["prompt"]
    assert "Pergunta de distribuicao" in captured["prompt"]
    assert "nao adicione percentual" in captured["prompt"]


def test_prompt_includes_domain_guidance_for_cid_c_and_contraceptive(monkeypatch, tmp_path):
    captured = {}

    class FakeAgent:
        def run_sync(self, prompt, *, deps):
            captured["prompt"] = prompt
            return SimpleNamespace(
                output=SqlPlan(
                    question="Quantas mortes de mulheres por cancer com CID C e contraceptivo 1 informado ocorreram?",
                    sql=(
                        "SELECT COUNT(*) AS mortes FROM internacoes "
                        "WHERE MORTE AND DIAG_PRINC LIKE 'C%'"
                    ),
                )
            )

    monkeypatch.setattr(
        sql_generator_module,
        "build_sql_plan_agent",
        lambda config: FakeAgent(),
    )
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
    )
    context = RetrievedContext(
        tables=["internacoes", "cid", "contraceptivos", "sexo"],
        columns=[
            "internacoes.DIAG_PRINC",
            "internacoes.CONTRACEP1",
            "internacoes.SEXO",
            "cid.CID",
            "sexo.SEXO",
            "sexo.DESCRICAO",
        ],
        table_context=[
            "table=internacoes\ncolumns=DIAG_PRINC, CONTRACEP1, SEXO",
            "table=cid\ncolumns=CID, DS_CAPITULO",
            "table=contraceptivos\ncolumns=CONTRACEPTIVO, DESCRICAO",
            "table=sexo\ncolumns=SEXO, DESCRICAO",
        ],
        retrieval_mode="test",
    )

    generate_sql_plan(
        "Quantas mortes de mulheres por cancer com CID C e contraceptivo 1 informado ocorreram?",
        context,
        Stage1Context(project_root=str(tmp_path)),
        config,
    )

    assert "internacoes.DIAG_PRINC LIKE 'C%'" in captured["prompt"]
    assert "internacoes.MORTE = TRUE" in captured["prompt"]
    assert "Nao conte apenas internacoes com diagnostico sem aplicar MORTE = TRUE" in captured[
        "prompt"
    ]
    assert "internacoes.SEXO IN (2, 3)" in captured["prompt"]
    assert "cid.DS_CAPITULO = 'Neoplasias'" in captured["prompt"]
    assert "contraceptivo 1" in captured["prompt"]
    assert "internacoes.CONTRACEP1" in captured["prompt"]
    assert "nao interprete como filtro CONTRACEP1 = 1" in captured["prompt"]


def test_prompt_includes_temporal_interval_shape_guidance(monkeypatch, tmp_path):
    captured = {}

    class FakeAgent:
        def run_sync(self, prompt, *, deps):
            captured["prompt"] = prompt
            return SimpleNamespace(
                output=SqlPlan(
                    question="Qual e o intervalo de datas disponivel na dimensao tempo?",
                    sql="SELECT MIN(data) AS primeira_data, MAX(data) AS ultima_data, COUNT(*) AS dias FROM tempo",
                )
            )

    monkeypatch.setattr(
        sql_generator_module,
        "build_sql_plan_agent",
        lambda config: FakeAgent(),
    )
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
    )

    generate_sql_plan(
        "Qual e o intervalo de datas disponivel na dimensao tempo?",
        RetrievedContext(tables=["tempo"], columns=["tempo.data"], table_context=["table=tempo"]),
        Stage1Context(project_root=str(tmp_path)),
        config,
    )

    assert "Pergunta de intervalo temporal" in captured["prompt"]
    assert "primeiro MIN" in captured["prompt"]
    assert "por ultimo COUNT(*)" in captured["prompt"]


def test_prompt_includes_canonical_parto_metric(monkeypatch, tmp_path):
    captured = {}

    class FakeAgent:
        def run_sync(self, prompt, *, deps):
            captured["prompt"] = prompt
            return SimpleNamespace(
                output=SqlPlan(
                    question="quantos partos aconteceram?",
                    sql=(
                        "SELECT COUNT(*) AS total_partos FROM internacoes "
                        "WHERE PROC_REA IN ('0310010039','0310010047','0310010055',"
                        "'0411010026','0411010034','0411010042')"
                    ),
                )
            )

    monkeypatch.setattr(sql_generator_module, "build_sql_plan_agent", lambda config: FakeAgent())
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
    )

    generate_sql_plan(
        "quantos partos aconteceram?",
        RetrievedContext(
            tables=["internacoes", "procedimentos"],
            columns=["internacoes.PROC_REA", "procedimentos.NOME_PROC"],
            table_context=[
                "table=internacoes\ncolumns=PROC_REA",
                "table=procedimentos\ncolumns=PROC_REA, NOME_PROC",
            ],
            retrieval_mode="test",
        ),
        Stage1Context(project_root=str(tmp_path)),
        config,
    )

    assert "metrica canonica de partos" in captured["prompt"]
    assert "internacoes.PROC_REA IN" in captured["prompt"]
    assert "0310010039" in captured["prompt"]
    assert "Nao use DIAG_PRINC LIKE 'O8%'" in captured["prompt"]
