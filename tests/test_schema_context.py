from health_system_chatbot.artifacts import load_stage1_context
from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import RetrievedContext
import health_system_chatbot.schema_context as schema_context_module
from health_system_chatbot.schema_context import retrieve_context


def test_city_question_adds_municipality_dimension_for_hospital_geography():
    ctx = load_stage1_context()

    retrieved = retrieve_context(
        "Quais diagnosticos causaram mortes em Porto Alegre?",
        ctx,
        use_vector=False,
    )

    assert "municipios" in retrieved.tables
    assert "municipios.NO_MUNICIPIO" in retrieved.columns
    assert any(
        policy.left == "hospital.MUNIC_MOV"
        and policy.right == "municipios.CO_MUNICIPIO_6D"
        for policy in retrieved.join_policies
    )


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
    assert "internacoes" in retrieved.tables


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
    assert any("internacoes.MORTE" in metric.columns for metric in retrieved.business_metrics)
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
    assert any("internacoes.MORTE" in metric.columns for metric in retrieved.business_metrics)


def test_retrieval_adds_parto_context():
    ctx = load_stage1_context()

    retrieved = retrieve_context(
        "quantos partos aconteceram?",
        ctx,
        use_vector=False,
    )

    assert "internacoes" in retrieved.tables
    assert "procedimentos" in retrieved.tables
    metric_names = {metric.name for metric in retrieved.business_metrics}
    assert "total_partos" in metric_names
    assert any(
        hint.table == "procedimentos"
        and hint.column == "PROC_REA"
        and hint.value == "0310010039"
        for hint in retrieved.value_hints
    )


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
        con.execute("CREATE TABLE internacoes (CAR_INT TINYINT)")
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

    assert "internacoes" in retrieved.tables
    assert "marca_uti" in retrieved.tables
    assert "marca_uti.DESCRICAO" in retrieved.columns


def test_retrieval_adds_cid_cancer_value_hints(tmp_path):
    import duckdb

    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE cid (CID VARCHAR, DESCRICAO VARCHAR, DS_CAPITULO VARCHAR)"
        )
        con.execute(
            "INSERT INTO cid VALUES ('C00', 'Neopl malig do labio', 'II. Neoplasias [tumores]')"
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
        hint.table == "cid"
        and hint.column == "CID"
        and hint.value == "C00"
        and "II. Neoplasias [tumores]" in hint.label
        for hint in result.value_hints
    )


def test_retrieval_adds_generic_cid_group_hint_for_diagnosis_parto(tmp_path):
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
        hint.table == "cid"
        and hint.column == "DS_GRUPO"
        and hint.value == "O80-O84 Parto"
        for hint in retrieved.value_hints
    )


def test_retrieval_adds_generic_cid_chapter_hint_for_infections(tmp_path):
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
        hint.table == "cid"
        and hint.column == "DS_CAPITULO"
        and "infecciosas" in hint.value
        for hint in retrieved.value_hints
    )
