from health_system_chatbot.artifacts import load_stage1_context
from health_system_chatbot.catalogs.models import CatalogDecision
from health_system_chatbot.models import SqlPlan
from health_system_chatbot.sql_validator import validate_sql


def test_blocks_mutating_sql():
    ctx = load_stage1_context()

    result = validate_sql("DROP TABLE internacoes", ctx)

    assert not result.is_valid
    assert any("DROP" in error for error in result.errors)


def test_allows_simple_select():
    ctx = load_stage1_context()

    result = validate_sql("SELECT COUNT(*) AS total FROM internacao", ctx)

    assert result.is_valid
    assert result.safe_sql == "SELECT COUNT(*) AS total FROM internacao"


def test_blocks_rejected_relationship_for_business_query():
    ctx = load_stage1_context()
    sql = (
        "SELECT r.DESCRICAO, COUNT(*) "
        "FROM internacao i JOIN raca_cor r ON i.RACA_COR = r.RACA_COR "
        "GROUP BY 1"
    )

    result = validate_sql(sql, ctx, question="Quantas internacoes por raca cor?")

    assert result.is_valid
    assert any("Rejected relationship" in warning for warning in result.warnings)


def test_likely_municipality_join_requires_mapped_scope_or_left_join():
    ctx = load_stage1_context()
    sql = (
        "SELECT m.SG_UF, COUNT(*) "
        "FROM internacao i JOIN municipios m ON i.MUNIC_RES = m.CO_MUNICIPIO_6D "
        "GROUP BY 1"
    )

    invalid = validate_sql(sql, ctx, question="Internacoes por UF de residencia")
    assert invalid.is_valid
    assert any("Join requires LEFT JOIN" in warning for warning in invalid.warnings)

    plan = SqlPlan(
        question="Internacoes por UF de residencia mapeada",
        sql=sql,
        caveats=["Resultado restrito a internacoes com municipio de residencia mapeado."],
    )
    valid = validate_sql(sql, ctx, question=plan.question, plan=plan)
    assert valid.is_valid


def test_denominador_socioeconomico_counts_as_explicit_mapped_scope():
    ctx = load_stage1_context()
    sql = (
        "SELECT m.SG_UF, se.NU_ANO AS ano, SUM(se.QT_POPULACAO) AS populacao, "
        "COUNT(i.N_AIH) AS internacoes "
        "FROM socioeconomico se "
        "JOIN municipios m ON se.CO_MUNICIPIO_6D = m.CO_MUNICIPIO_6D "
        "LEFT JOIN internacao i "
        "ON i.MUNIC_RES = se.CO_MUNICIPIO_6D AND year(i.DT_INTER) = se.NU_ANO "
        "GROUP BY 1, 2"
    )

    result = validate_sql(
        sql,
        ctx,
        question=(
            "Qual e a populacao e o total de internacoes por UF e ano "
            "quando ha denominador socioeconomico?"
        ),
    )

    assert result.is_valid


def test_rejects_text_literal_filter_on_numeric_municipality_code():
    ctx = load_stage1_context()
    sql = (
        "SELECT COUNT(*) "
        "FROM internacao i JOIN hospital h ON i.CNES = h.CNES "
        "WHERE h.MUNIC_MOV = 'Porto Alegre'"
    )

    result = validate_sql(sql, ctx, question="Mortes em Porto Alegre")

    assert not result.is_valid
    assert any("hospital.MUNIC_MOV" in error for error in result.errors)
    assert any("text literal" in error for error in result.errors)


def test_rejects_unknown_columns_before_execution():
    ctx = load_stage1_context()
    sql = (
        "SELECT COUNT(*) AS total_partos "
        "FROM internacao "
        "WHERE CID_MAE LIKE 'O80%' OR DIAG_SECUN10 LIKE 'O80%'"
    )

    result = validate_sql(sql, ctx, question="quantos partos aconteceram?")

    assert not result.is_valid
    assert any("CID_MAE" in error for error in result.errors)
    assert any("DIAG_SECUN10" in error for error in result.errors)


def test_rejects_description_column_when_question_requests_raw_codes():
    ctx = load_stage1_context()
    sql = (
        "SELECT c.CID, c.DESCRICAO, COUNT(*) AS internacoes "
        "FROM internacao i JOIN cid c ON i.DIAG_PRINC = c.CID "
        "GROUP BY 1, 2"
    )

    result = validate_sql(
        sql,
        ctx,
        question="Quais codigos de diagnostico principal foram mais frequentes?",
    )

    assert result.is_valid
    assert any("raw codes" in warning for warning in result.warnings)


def test_runtime_catalog_allows_staging_and_blocks_absent_legacy_table(tmp_path):
    import duckdb

    db_path = tmp_path / "runtime.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE _staging_internacoes (CAR_INT TINYINT)")
        con.execute("INSERT INTO _staging_internacoes VALUES (1)")
        con.execute("CREATE TABLE internacoes (CAR_INT TINYINT)")
        con.execute("INSERT INTO internacoes VALUES (1)")
    finally:
        con.close()

    ctx = load_stage1_context(db_path=db_path)

    staging = validate_sql("SELECT COUNT(*) FROM _staging_internacoes", ctx)
    assert staging.is_valid

    legacy = validate_sql("SELECT COUNT(*) FROM internacao_procedimento", ctx)
    assert not legacy.is_valid
    assert any("internacao_procedimento" in error for error in legacy.errors)


def test_rejects_raw_dimension_code_when_business_description_is_required():
    ctx = load_stage1_context()
    sql = "SELECT CAR_INT, COUNT(*) AS internacoes FROM internacao GROUP BY 1"

    result = validate_sql(
        sql,
        ctx,
        question="Como as internacoes se distribuem por carater de internacao?",
    )

    assert result.is_valid
    assert any("car_int.DESCRICAO" in warning for warning in result.warnings)


def test_allows_raw_dimension_code_when_user_requests_codes():
    ctx = load_stage1_context()
    sql = "SELECT CAR_INT, COUNT(*) AS internacoes FROM internacao GROUP BY 1"

    result = validate_sql(
        sql,
        ctx,
        question="Como as internacoes se distribuem por codigo de carater de internacao?",
    )

    assert result.is_valid


def test_rejects_audit_shape_without_denominator():
    ctx = load_stage1_context()
    sql = (
        "SELECT COUNT(*) AS internacoes_sem_correspondencia_instrucao "
        "FROM internacao i LEFT JOIN instrucao d ON i.INSTRU = d.INSTRU "
        "WHERE i.INSTRU IS NOT NULL AND d.INSTRU IS NULL"
    )

    result = validate_sql(
        sql,
        ctx,
        question="Auditoria: quantas internacoes tem instrucao sem correspondencia na dimensao?",
    )

    assert result.is_valid
    assert any("both unmatched and total" in warning for warning in result.warnings)


def test_rejects_audit_where_null_that_drops_denominator():
    ctx = load_stage1_context()
    sql = (
        "SELECT COUNT(*) AS sem_correspondencia, COUNT(*) AS internacoes "
        "FROM internacao i LEFT JOIN cbor c ON i.CBOR = c.CBOR "
        "WHERE i.CBOR IS NOT NULL AND c.CBOR IS NULL"
    )

    result = validate_sql(
        sql,
        ctx,
        question="Auditoria: quantas internacoes tem CBOR sem correspondencia na dimensao ocupacional?",
    )

    assert result.is_valid
    assert any("full denominator" in warning for warning in result.warnings)


def test_ranking_without_explicit_n_does_not_invent_limit():
    ctx = load_stage1_context()
    sql = (
        "SELECT n.DESCRICAO AS nacionalidade, COUNT(*) AS internacoes "
        "FROM internacao i JOIN nacionalidade n ON i.NACIONAL = n.NACIONAL "
        "GROUP BY 1 ORDER BY internacoes DESC"
    )

    result = validate_sql(sql, ctx, question="Quais nacionalidades tiveram mais internacoes?")

    assert result.is_valid
    assert not any("LIMIT" in warning for warning in result.warnings)


def test_rejects_raw_sex_code_for_business_readable_ranking():
    ctx = load_stage1_context()
    sql = (
        "WITH base AS ("
        "SELECT m.SG_UF, i.SEXO, COUNT(*) AS internacoes "
        "FROM internacao i JOIN municipios m ON i.MUNIC_RES = m.CO_MUNICIPIO_6D "
        "GROUP BY 1, 2"
        ") SELECT SG_UF, SEXO, internacoes FROM base ORDER BY internacoes DESC LIMIT 20"
    )

    result = validate_sql(
        sql,
        ctx,
        question="Quais UFs e sexos tiveram mais internacoes por residencia mapeada?",
    )

    assert result.is_valid
    assert any("sexo.DESCRICAO" in warning for warning in result.warnings)


def test_validator_has_no_cid_specific_filter_rule():
    ctx = load_stage1_context()
    sql = (
        "SELECT year(DT_INTER) AS ano, "
        "COUNT(*) FILTER (WHERE MORTE AND DIAG_PRINC LIKE 'C%') AS mortes "
        "FROM internacao GROUP BY 1 ORDER BY 1"
    )

    result = validate_sql(
        sql,
        ctx,
        question="Quantas mortes hospitalares com diagnostico principal CID C ocorreram por ano?",
    )

    assert result.is_valid
    assert not any("CID C" in warning for warning in result.warnings)


def test_validator_has_no_contraceptive_specific_join_rule():
    ctx = load_stage1_context()
    sql = (
        "SELECT c.DESCRICAO AS contraceptivo, COUNT(*) AS internacoes "
        "FROM internacao i LEFT JOIN contraceptivos c ON i.CONTRACEP1 = c.CONTRACEPTIVO "
        "GROUP BY 1 ORDER BY internacoes DESC"
    )

    result = validate_sql(
        sql,
        ctx,
        question="Como as internacoes com contraceptivo 1 informado se distribuem por tipo de contraceptivo?",
    )

    assert result.is_valid
    assert not any("Contraceptive" in warning for warning in result.warnings)


def test_validator_has_no_phrase_specific_mix_order_rule():
    ctx = load_stage1_context()
    sql = (
        "SELECT comp.DESCRICAO AS complexidade, car.DESCRICAO AS carater, "
        "COUNT(*) AS internacoes "
        "FROM internacao i "
        "JOIN complexidade comp ON i.COMPLEX = comp.COMPLEX "
        "JOIN car_int car ON i.CAR_INT = car.CAR_INT "
        "GROUP BY 1, 2 ORDER BY carater, internacoes DESC"
    )

    result = validate_sql(sql, ctx, question="Qual e o mix de complexidade por carater de internacao?")

    assert result.is_valid
    assert not any("Mix de complexidade" in warning for warning in result.warnings)


def test_cancer_city_question_is_not_blocked_by_advisory_schema_warnings():
    ctx = load_stage1_context()
    sql = (
        "SELECT year(i.DT_INTER) AS ano, COUNT(*) AS mortes_cancer "
        "FROM internacao i "
        "JOIN municipios m ON i.MUNIC_RES = m.CO_MUNICIPIO_6D "
        "WHERE i.MORTE = TRUE "
        "AND i.IDADE > 50 "
        "AND i.SEXO IN (2, 3) "
        "AND i.DIAG_PRINC LIKE 'C%' "
        "AND m.NO_MUNICIPIO = 'Santa Maria' "
        "AND m.SG_UF = 'RS' "
        "GROUP BY 1 ORDER BY 1"
    )

    result = validate_sql(
        sql,
        ctx,
        question="Quantas mulheres acima de 50 anos morreram por cancer na cidade de Santa Maria ao longo dos anos?",
    )

    assert result.is_valid
    assert result.errors == []
    assert result.safe_sql == sql


def test_catalog_decision_warns_when_group_becomes_short_code_list():
    ctx = load_stage1_context()
    sql = (
        "SELECT COUNT(*) AS internacoes "
        "FROM internacao "
        "WHERE DIAG_PRINC IN ('O80', 'O81', 'O82', 'O83', 'O84')"
    )
    plan = SqlPlan(
        question="Quantas internacoes com diagnostico de parto?",
        sql=sql,
        catalog_decisions=[
            CatalogDecision(
                catalog="cid",
                query="parto",
                selected_candidate_label="O80-O84 Parto",
                selected_filter="cid.DS_GRUPO = 'O80-O84 Parto'",
                confidence="high",
            )
        ],
    )

    result = validate_sql(sql, ctx, question=plan.question, plan=plan)

    assert result.is_valid
    assert any("CID group catalog decision" in warning for warning in result.warnings)


def test_warns_when_counting_rows_of_internacao_procedimento():
    ctx = load_stage1_context()

    occurrences = validate_sql(
        "SELECT COUNT(*) AS total FROM internacao_procedimento WHERE PROC_REA = '0411010034'",
        ctx,
        question="Quantas internacoes tiveram parto cesariano?",
    )
    distinct = validate_sql(
        "SELECT COUNT(DISTINCT N_AIH) AS total FROM internacao_procedimento WHERE PROC_REA = '0411010034'",
        ctx,
        question="Quantas internacoes tiveram parto cesariano?",
    )

    assert any("COUNT(DISTINCT N_AIH)" in warning for warning in occurrences.warnings)
    assert not any("COUNT(DISTINCT N_AIH)" in warning for warning in distinct.warnings)


_PARTO_CODES = "('0310010039','0310010047','0310010055','0411010026','0411010034','0411010042')"


def test_unqualified_join_key_is_resolved_per_select_scope():
    # Counting births needs internacao and internacao_procedimento, which both
    # have N_AIH. Each of these is valid DuckDB and used to be rejected as an
    # "ambiguous column" because resolution looked at every table in the query.
    ctx = load_stage1_context()
    question = "Demonstre em um grafico a quantidade de partos anuais feitos no Rio Grande do Sul"
    variants = [
        f"WITH p AS (SELECT DISTINCT N_AIH FROM internacao_procedimento WHERE PROC_REA IN {_PARTO_CODES}) "
        "SELECT year(i.DT_INTER) AS ano, COUNT(*) AS partos FROM internacao i "
        "JOIN p ON p.N_AIH = i.N_AIH GROUP BY 1 ORDER BY 1",
        "SELECT year(i.DT_INTER) AS ano, COUNT(DISTINCT N_AIH) AS partos FROM internacao i "
        f"JOIN internacao_procedimento ip USING (N_AIH) WHERE ip.PROC_REA IN {_PARTO_CODES} "
        "GROUP BY 1 ORDER BY 1",
        "SELECT year(i.DT_INTER) AS ano, COUNT(*) AS partos FROM internacao i WHERE i.N_AIH IN "
        f"(SELECT N_AIH FROM internacao_procedimento WHERE PROC_REA IN {_PARTO_CODES}) "
        "GROUP BY 1 ORDER BY 1",
        "SELECT year(i.DT_INTER) AS ano, COUNT(*) AS partos FROM internacao i WHERE EXISTS "
        "(SELECT 1 FROM internacao_procedimento ip WHERE N_AIH = i.N_AIH "
        f"AND PROC_REA IN {_PARTO_CODES}) GROUP BY 1 ORDER BY 1",
        # Shape the agent produced for "partos espontaneo cefalico anuais no RS":
        # the outer N_AIH binds to the CTE, not to the tables inside it.
        "WITH base AS (SELECT EXTRACT(YEAR FROM i.DT_INTER) AS ano, i.N_AIH FROM internacao i "
        "JOIN municipios m_res ON i.MUNIC_RES = m_res.CO_MUNICIPIO_6D WHERE m_res.SG_UF = 'RS' "
        "AND EXISTS (SELECT 1 FROM internacao_procedimento ip WHERE ip.N_AIH = i.N_AIH "
        f"AND ip.PROC_REA IN {_PARTO_CODES})) "
        "SELECT ano, COUNT(DISTINCT N_AIH) AS total_partos FROM base GROUP BY ano ORDER BY ano",
    ]

    for sql in variants:
        result = validate_sql(sql, ctx, question=question)
        assert not any("column" in error.lower() for error in result.errors), (sql, result.errors)


def test_really_ambiguous_and_unknown_columns_are_still_rejected():
    ctx = load_stage1_context()

    ambiguous = validate_sql(
        "SELECT N_AIH FROM internacao i JOIN internacao_procedimento ip ON ip.N_AIH = i.N_AIH LIMIT 5",
        ctx,
        question="Liste internacoes",
    )
    unknown = validate_sql(
        "SELECT COUNT(*) AS total FROM internacao WHERE PROC_REA = '0411010034'",
        ctx,
        question="Quantas cesarianas?",
    )

    assert "Ambiguous column: N_AIH; qualify it with a table alias." in ambiguous.errors
    assert "Unknown column: PROC_REA" in unknown.errors
