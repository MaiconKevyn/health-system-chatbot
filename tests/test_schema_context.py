from health_system_chatbot.artifacts import load_stage1_context
from health_system_chatbot.config import ChatbotConfig, load_config
from health_system_chatbot.models import RetrievedContext
import health_system_chatbot.schema_context as schema_context_module
from health_system_chatbot.schema_context import retrieve_context


def test_city_question_offers_residence_and_hospital_geography():
    # sihrd9 ships a populated `hospital` table (CNES -> hospital covers 100% of
    # admissions), so a bare city mention is ambiguous between residence and
    # hospital geography and both join paths must reach the prompt.
    # Requires db_path so the runtime merge (which drops empty tables) actually
    # runs, same as every real call site.
    config = load_config()
    ctx = load_stage1_context(config.project_root, db_path=config.db_path)

    retrieved = retrieve_context(
        "Quais diagnosticos causaram mortes em Porto Alegre?",
        ctx,
        use_vector=False,
    )

    assert "municipios" in retrieved.tables
    assert "municipios.NO_MUNICIPIO" in retrieved.columns
    assert "internacao.MUNIC_RES" in retrieved.columns
    assert "hospital" in retrieved.tables
    policies = {(policy.left, policy.right) for policy in retrieved.join_policies}
    assert ("internacao.MUNIC_RES", "municipios.CO_MUNICIPIO_6D") in policies
    assert ("internacao.CNES", "hospital.CNES") in policies
    assert ("hospital.MUNIC_MOV", "municipios.CO_MUNICIPIO_6D") in policies


def test_pydantic_ai_auto_retrieval_uses_keyword_even_with_openai_key(monkeypatch, tmp_path):
    ctx = load_stage1_context()

    def fail_vector(*args, **kwargs):
        raise AssertionError("vector retrieval should not be called for pydantic_ai auto mode")

    monkeypatch.setattr(schema_context_module, "retrieve_context_with_index", fail_vector)
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
        schema_retrieval_mode="auto",
    )

    retrieved = retrieve_context(
        "Quantas internacoes existem na tabela principal?",
        ctx,
        config=config,
    )

    assert retrieved.retrieval_mode == "schema_keyword"
    assert "internacao" in retrieved.tables


def test_explicit_llamaindex_vector_mode_uses_vector_retrieval(monkeypatch, tmp_path):
    ctx = load_stage1_context()

    def fake_vector(*args, **kwargs):
        return RetrievedContext(
            tables=["internacoes"],
            table_context=["table=internacoes"],
            retrieval_mode="llamaindex_vector",
        )

    monkeypatch.setattr(schema_context_module, "retrieve_context_with_index", fake_vector)
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key="test",
        agent_framework="pydantic_ai",
        schema_retrieval_mode="llamaindex_vector",
    )

    retrieved = retrieve_context(
        "Quantas internacoes existem na tabela principal?",
        ctx,
        config=config,
    )

    assert retrieved.retrieval_mode == "llamaindex_vector"


def test_retrieval_adds_business_metrics_and_query_examples():
    ctx = load_stage1_context()

    retrieved = retrieve_context(
        "Qual foi a taxa bruta de mortalidade hospitalar por ano?",
        ctx,
        use_vector=False,
    )

    metric_names = {metric.name for metric in retrieved.business_metrics}
    assert "taxa_mortalidade_hospitalar" in metric_names
    assert any("internacao.MORTE" in metric.columns for metric in retrieved.business_metrics)
    assert retrieved.query_examples
    assert any(example.sql for example in retrieved.query_examples)


def test_retrieval_treats_morreram_as_death_metric():
    ctx = load_stage1_context()

    retrieved = retrieve_context(
        "Quantas mulheres morreram por cancer ao longo dos anos?",
        ctx,
        use_vector=False,
    )

    metric_names = {metric.name for metric in retrieved.business_metrics}
    assert "total_mortes_hospitalares" in metric_names
    assert any("internacao.MORTE" in metric.columns for metric in retrieved.business_metrics)


def test_retrieval_adds_parto_context():
    ctx = load_stage1_context()

    retrieved = retrieve_context(
        "quantos partos aconteceram?",
        ctx,
        use_vector=False,
    )

    assert "internacao" in retrieved.tables
    assert "internacao_procedimento" in retrieved.tables
    assert "procedimentos" in retrieved.tables
    metric_names = {metric.name for metric in retrieved.business_metrics}
    assert "total_partos" in metric_names
    assert any(
        hint.table == "procedimentos"
        and hint.column == "PROC_REA"
        and hint.value == "0310010039"
        for hint in retrieved.value_hints
    )


def test_retrieval_does_not_prioritize_procedure_metric_for_internacoes_por_parto():
    ctx = load_stage1_context()

    retrieved = retrieve_context(
        "Qual a evolucao anual das internacoes por parto cesariano?",
        ctx,
        use_vector=False,
    )

    metric_names = {metric.name for metric in retrieved.business_metrics}
    assert "total_partos" not in metric_names
    assert "partos_cesarianos" not in metric_names
    assert "total_internacoes" in metric_names


def test_spontaneous_cephalic_deliveries_retrieve_diagnosis_and_place_of_care():
    retrieved = retrieve_context(
        "me mostre em um gráfico a quantidade de partos espontâneo cefálico anuais feitos no rio grande do sul",
        load_stage1_context(),
        use_vector=False,
    )

    assert {"internacao", "cid", "hospital", "municipios"} <= set(retrieved.tables)
    assert {"spontaneous_cephalic_delivery_v1", "care_location_v1"} <= set(retrieved.semantic_rule_ids)
    assert retrieved.question_contract.time.grain == "year"
    assert all(metric.name != "total_partos" for metric in retrieved.business_metrics)
    assert all(hint.column != "PROC_REA" for hint in retrieved.value_hints)


def test_retrieval_adds_municipality_value_hints(tmp_path):
    import duckdb

    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE municipios (NO_MUNICIPIO VARCHAR, SG_UF VARCHAR)")
        con.execute("INSERT INTO municipios VALUES ('Porto Alegre', 'RS')")
    finally:
        con.close()

    ctx = load_stage1_context()
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=db_path,
        openai_api_key=None,
        agent_framework="pydantic_ai",
    )

    retrieved = retrieve_context(
        "Quais diagnosticos causaram mortes em Porto Alegre?",
        ctx,
        config=config,
        use_vector=False,
    )

    assert any(
        hint.table == "municipios"
        and hint.column == "NO_MUNICIPIO"
        and hint.value == "Porto Alegre"
        and hint.label == "RS"
        for hint in retrieved.value_hints
    )


def test_retrieval_extracts_santa_maria_from_long_city_phrase(tmp_path):
    import duckdb

    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE municipios (NO_MUNICIPIO VARCHAR, SG_UF VARCHAR)")
        con.execute("INSERT INTO municipios VALUES ('Santa Maria', 'RS'), ('Santa Maria', 'RN')")
    finally:
        con.close()

    ctx = load_stage1_context()
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=db_path,
        openai_api_key=None,
        agent_framework="pydantic_ai",
    )

    retrieved = retrieve_context(
        "quantas mulheres acima de 50 anos morreram por cancer na cidade de Santa Maria ao longo dos anos?",
        ctx,
        config=config,
        use_vector=False,
    )

    santa_maria_hints = [
        hint
        for hint in retrieved.value_hints
        if hint.table == "municipios"
        and hint.column == "NO_MUNICIPIO"
        and hint.value == "Santa Maria"
    ]
    assert {hint.label for hint in santa_maria_hints} == {"RS", "RN"}


def test_runtime_retrieval_adds_staging_table(tmp_path):
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

    retrieved = retrieve_context(
        "Quantos registros existem na tabela de staging de internacoes?",
        ctx,
        use_vector=False,
    )

    assert "_staging_internacoes" in retrieved.tables


def test_retrieval_adds_dimension_table_for_business_readable_distribution():
    ctx = load_stage1_context()

    retrieved = retrieve_context(
        "Como as internacoes se distribuem por marca de UTI?",
        ctx,
        use_vector=False,
    )

    assert "internacao" in retrieved.tables
    assert "marca_uti" in retrieved.tables
    assert "marca_uti.DESCRICAO" in retrieved.columns


def test_retrieval_adds_cid_cancer_catalog_candidates(tmp_path):
    import duckdb

    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE cid ("
            "CID VARCHAR, DESCRICAO VARCHAR, DS_CATEGORIA VARCHAR, "
            "DS_GRUPO VARCHAR, DS_CAPITULO VARCHAR)"
        )
        con.execute(
            "INSERT INTO cid VALUES ("
            "'C00', 'Neopl malig do labio', 'Neopl malig do labio', "
            "'C00-C14 Neoplasias malignas do labio, cavidade oral e faringe', "
            "'II. Neoplasias [tumores]')"
        )
    finally:
        con.close()

    ctx = load_stage1_context()
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=db_path,
        openai_api_key=None,
        agent_framework="pydantic_ai",
    )

    retrieved = RetrievedContext(tables=["cid"])
    from health_system_chatbot.context_retrieval import enrich_retrieved_context

    result = enrich_retrieved_context(
        question="Quantas mortes com CID C por cancer?",
        ctx=ctx,
        retrieved=retrieved,
        config=config,
    )

    assert any(
        candidate.catalog == "cid"
        and candidate.filter.column in {"DIAG_PRINC", "DS_GRUPO", "DS_CAPITULO"}
        and (
            candidate.filter.value == "C%"
            or "Neoplasias" in str(candidate.filter.value)
            or str(candidate.code).startswith("C")
        )
        for candidate in result.catalog_candidates
    )


def test_retrieval_adds_generic_cid_group_candidate_for_diagnosis_parto(tmp_path):
    import duckdb

    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE internacoes (DIAG_PRINC VARCHAR)")
        con.execute(
            "CREATE TABLE cid ("
            "CID VARCHAR, DESCRICAO VARCHAR, TP_NIVEL VARCHAR, RESTRSEXO VARCHAR, "
            "DS_CATEGORIA VARCHAR, DS_GRUPO VARCHAR, DS_CAPITULO VARCHAR)"
        )
        con.execute(
            "INSERT INTO cid VALUES "
            "('O80', 'Parto unico espontaneo', NULL, NULL, "
            "'Parto unico espontaneo', 'O80-O84 Parto', 'XV. Gravidez, parto e puerperio'),"
            "('O60', 'Parto pre-termo', NULL, NULL, "
            "'Parto pre-termo', 'O60-O75 Complicacoes do trabalho de parto e do parto', "
            "'XV. Gravidez, parto e puerperio')"
        )
    finally:
        con.close()

    ctx = load_stage1_context(db_path=db_path)
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=db_path,
        openai_api_key=None,
        agent_framework="pydantic_ai",
    )

    retrieved = retrieve_context(
        "Quantas internacoes com diagnostico de parto aconteceram?",
        ctx,
        config=config,
        use_vector=False,
    )

    assert "cid" in retrieved.tables
    assert "total_partos" not in {metric.name for metric in retrieved.business_metrics}
    assert any(
        candidate.catalog == "cid"
        and candidate.filter.column == "DS_GRUPO"
        and candidate.filter.value == "O80-O84 Parto"
        for candidate in retrieved.catalog_candidates
    )


def test_retrieval_adds_generic_cid_chapter_candidate_for_infections(tmp_path):
    import duckdb

    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE internacoes (DIAG_PRINC VARCHAR, MORTE BOOLEAN)")
        con.execute(
            "CREATE TABLE cid ("
            "CID VARCHAR, DESCRICAO VARCHAR, TP_NIVEL VARCHAR, RESTRSEXO VARCHAR, "
            "DS_CATEGORIA VARCHAR, DS_GRUPO VARCHAR, DS_CAPITULO VARCHAR)"
        )
        con.execute(
            "INSERT INTO cid VALUES "
            "('A00', 'Colera', NULL, NULL, 'Colera', "
            "'A00-A09 Doencas infecciosas intestinais', "
            "'I. Algumas doencas infecciosas e parasitarias')"
        )
    finally:
        con.close()

    ctx = load_stage1_context(db_path=db_path)
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=db_path,
        openai_api_key=None,
        agent_framework="pydantic_ai",
    )

    retrieved = retrieve_context(
        "Quantas mortes por infeccoes?",
        ctx,
        config=config,
        use_vector=False,
    )

    assert "cid" in retrieved.tables
    assert any(
        candidate.catalog == "cid"
        and candidate.filter.column == "DS_CAPITULO"
        and "infecciosas" in str(candidate.filter.value)
        for candidate in retrieved.catalog_candidates
    )
