from pathlib import Path

import duckdb
import pytest

from health_system_chatbot.artifacts import load_stage1_context
from health_system_chatbot.sql_validator import validate_sql


def test_explicit_top_n_is_enforced_without_defaulting_other_rankings():
    ctx = load_stage1_context()
    missing = validate_sql(
        "SELECT CNES, COUNT(*) AS n FROM internacao GROUP BY 1 ORDER BY n DESC",
        ctx,
        question="Quais são os 3 hospitais com mais internações?",
    )
    open_ended = validate_sql(
        "SELECT CNES, COUNT(*) AS n FROM internacao GROUP BY 1 ORDER BY n DESC",
        ctx,
        question="Quais hospitais tiveram mais internações?",
    )

    assert not missing.is_valid
    assert any("top 3" in error for error in missing.errors)
    assert open_ended.is_valid


def test_implicit_limit_is_warning_not_hidden_requirement():
    ctx = load_stage1_context()
    result = validate_sql(
        "SELECT CNES, COUNT(*) AS n FROM internacao GROUP BY 1 ORDER BY n DESC LIMIT 10",
        ctx,
        question="Quais hospitais tiveram mais internações?",
    )

    assert result.is_valid
    assert any("no explicit top-N" in warning for warning in result.warnings)


def test_partitioned_ranking_requires_explicit_per_group_language():
    ctx = load_stage1_context()
    sql = (
        "WITH x AS (SELECT CNES, ROW_NUMBER() OVER (PARTITION BY ESPEC ORDER BY CNES) AS rn "
        "FROM internacao) SELECT * FROM x WHERE rn <= 3"
    )
    result = validate_sql(
        sql,
        ctx,
        question="Quais são os 3 hospitais com mais internações?",
    )

    assert result.is_valid
    assert any("partitions a ranking" in warning for warning in result.warnings)


def test_join_on_aggregate_measure_is_rejected():
    ctx = load_stage1_context()
    sql = (
        "WITH h AS (SELECT CNES, COUNT(*) AS volume FROM internacao GROUP BY CNES), "
        "q AS (SELECT volume, NTILE(4) OVER (ORDER BY volume) AS quartil FROM h) "
        "SELECT q.quartil, COUNT(*) FROM q JOIN h ON h.volume = q.volume GROUP BY 1"
    )
    result = validate_sql(sql, ctx, question="Distribuição por quartil")

    assert not result.is_valid
    assert any("aggregated measure" in error for error in result.errors)


def test_percentile_on_aggregated_measure_is_rejected():
    ctx = load_stage1_context()
    sql = (
        "WITH base AS (SELECT DIAG_PRINC, SUM(VAL_TOT) AS total FROM internacao GROUP BY 1), "
        "lim AS (SELECT quantile_cont(total, 0.99) AS p99 FROM base) "
        "SELECT * FROM base, lim WHERE total > p99"
    )
    result = validate_sql(sql, ctx, question="Quais grupos estão acima do percentil 99?")

    assert not result.is_valid
    assert any("Percentile" in error for error in result.errors)


def test_semantic_rule_rejects_substring_uti_filter():
    ctx = load_stage1_context()
    sql = (
        "SELECT COUNT(*) FROM internacao i JOIN marca_uti m ON i.MARCA_UTI=m.MARCA_UTI "
        "WHERE m.DESCRICAO LIKE '%UTI%'"
    )
    result = validate_sql(sql, ctx, question="Quantas internações usaram UTI?")

    assert not result.is_valid
    assert any("uti_usage_v1" in error for error in result.errors)


def test_binder_preflight_rejects_ambiguous_alias(tmp_path: Path):
    db = tmp_path / "binder.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("CREATE TABLE fact (sexo INTEGER)")
        con.execute("CREATE TABLE dim (sexo INTEGER, descricao VARCHAR)")
        con.execute("INSERT INTO fact VALUES (1)")
        con.execute("INSERT INTO dim VALUES (1, 'x')")
    finally:
        con.close()
    ctx = load_stage1_context(db_path=db)
    sql = "SELECT sexo FROM fact f JOIN dim d ON f.sexo=d.sexo"

    result = validate_sql(sql, ctx, question="Sexo", db_path=db)

    assert not result.is_valid
    assert any("binder" in error.lower() or "ambiguous" in error.lower() for error in result.errors)


def test_missing_required_source_is_rejected_before_fabricated_rate():
    ctx = load_stage1_context()
    result = validate_sql(
        "SELECT MUNIC_RES, COUNT(*) * 1000.0 AS taxa FROM internacao GROUP BY 1",
        ctx,
        question="Qual a taxa de internação por mil habitantes por município?",
    )

    assert not result.is_valid
    assert any("Required source" in error for error in result.errors)


def test_quarter_of_year_contract_rejects_extra_year_grain():
    ctx = load_stage1_context()
    result = validate_sql(
        "SELECT EXTRACT(YEAR FROM DT_INTER) AS ano, "
        "EXTRACT(QUARTER FROM DT_INTER) AS trimestre, COUNT(*) "
        "FROM internacao GROUP BY 1, 2",
        ctx,
        question="Qual o total de internações em cada trimestre do ano?",
    )

    assert not result.is_valid
    assert any("adds year" in error for error in result.errors)


@pytest.mark.parametrize(
    "year_expression",
    [
        "EXTRACT(YEAR FROM DT_INTER)",
        "year(DT_INTER)",
        "date_part('year', DT_INTER)",
        "date_trunc('year', DT_INTER)",
        "strftime(DT_INTER, '%Y')",
    ],
)
def test_yearly_grain_accepts_equivalent_duckdb_forms(year_expression):
    ctx = load_stage1_context()
    result = validate_sql(
        f"SELECT {year_expression} AS ano, COUNT(*) AS internacoes "
        "FROM internacao GROUP BY 1 ORDER BY 1",
        ctx,
        question="Quantas internações ocorreram por ano?",
    )

    assert result.is_valid, result.errors


def test_yearly_grain_accepts_calendar_dimension_column():
    ctx = load_stage1_context()
    result = validate_sql(
        "SELECT t.ano, COUNT(*) AS internacoes "
        "FROM internacao i JOIN tempo t ON i.DT_INTER = t.data GROUP BY 1 ORDER BY 1",
        ctx,
        question="Quantas internacoes ocorreram por ano usando a dimensao tempo?",
    )

    assert result.is_valid, result.errors


def test_yearly_grain_is_still_required_when_missing():
    ctx = load_stage1_context()
    result = validate_sql(
        "SELECT COUNT(*) AS internacoes FROM internacao",
        ctx,
        question="Quantas internações ocorreram por ano?",
    )

    assert not result.is_valid
    assert any("temporal grain year" in error for error in result.errors)


def test_age_question_does_not_require_yearly_grain():
    ctx = load_stage1_context()
    result = validate_sql(
        "SELECT COUNT(*) AS internacoes FROM internacao WHERE IDADE > 60",
        ctx,
        question="Quantas internações de pacientes com mais de 60 anos?",
    )

    assert result.is_valid, result.errors


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT EXTRACT(MONTH FROM DT_INTER) AS mes, COUNT(*) AS internacoes "
        "FROM internacao WHERE EXTRACT(YEAR FROM DT_INTER) = 2023 GROUP BY mes ORDER BY mes",
        "WITH base AS (SELECT year(DT_INTER) AS ano, month(DT_INTER) AS mes FROM internacao) "
        "SELECT mes, COUNT(*) AS internacoes FROM base WHERE ano = 2023 GROUP BY mes ORDER BY mes",
    ],
)
def test_year_used_only_as_filter_is_not_an_extra_grain(sql):
    ctx = load_stage1_context()
    result = validate_sql(sql, ctx, question="Qual o total de internacoes por mes em 2023?")

    assert result.is_valid, result.errors


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT year(DT_INTER) AS ano, quarter(DT_INTER) AS trimestre, COUNT(*) AS internacoes "
        "FROM internacao GROUP BY 1, 2",
        "WITH base AS (SELECT year(DT_INTER) AS ano_entrada, quarter(DT_INTER) AS trimestre, "
        "COUNT(*) AS internacoes FROM internacao GROUP BY 1, 2) "
        "SELECT ano_entrada, trimestre, internacoes FROM base",
    ],
)
def test_projected_year_is_rejected_for_quarter_of_year_in_any_form(sql):
    ctx = load_stage1_context()
    result = validate_sql(sql, ctx, question="Qual o total de internações em cada trimestre do ano?")

    assert not result.is_valid
    assert any("adds year" in error for error in result.errors)


def test_covid_rule_rejects_incomplete_catalog_concept():
    ctx = load_stage1_context()
    incomplete = validate_sql(
        "SELECT COUNT(*) FROM internacao WHERE DIAG_PRINC = 'B342'",
        ctx,
        question="Quantas internações por COVID ou coronavírus ocorreram?",
    )
    complete = validate_sql(
        "SELECT COUNT(*) FROM internacao WHERE DIAG_PRINC IN ('B342', 'B972')",
        ctx,
        question="Quantas internações por COVID ou coronavírus ocorreram?",
    )

    assert not incomplete.is_valid
    assert complete.is_valid


def test_annual_cephalic_deliveries_count_admissions_by_diagnosis_and_hospital_state():
    ctx = load_stage1_context()
    question = "Me mostre em um gráfico a quantidade de partos espontâneo cefálico anuais feitos no Rio Grande do Sul"
    sql = (
        "WITH base AS (SELECT year(i.DT_INTER) AS ano, i.N_AIH FROM internacao i "
        "JOIN hospital h ON h.CNES = i.CNES JOIN municipios m ON m.CO_MUNICIPIO_6D = h.MUNIC_MOV "
        "WHERE m.SG_UF = 'RS' AND i.DIAG_PRINC = 'O800') "
        "SELECT ano, COUNT(DISTINCT N_AIH) AS partos FROM base GROUP BY ano ORDER BY ano"
    )
    assert validate_sql(sql, ctx, question=question).is_valid

    wrong_subtype = sql.replace(
        "i.DIAG_PRINC = 'O800'",
        "EXISTS (SELECT 1 FROM internacao_procedimento ip "
        "WHERE ip.N_AIH = i.N_AIH AND ip.PROC_REA = '0310010039')",
    )
    result = validate_sql(wrong_subtype, ctx, question=question)
    assert any("spontaneous_cephalic_delivery" in error for error in result.errors)
    assert not any("N_AIH" in error for error in result.errors)
    assert validate_sql(wrong_subtype, ctx, question="Partos normais anuais feitos no RS").is_valid

    by_residence = sql.replace("h.MUNIC_MOV", "i.MUNIC_RES")
    result = validate_sql(by_residence, ctx, question=question)
    assert any("care_location" in error for error in result.errors)
    assert validate_sql(by_residence, ctx, question="Partos espontâneos cefálicos de residentes no RS por ano").is_valid
