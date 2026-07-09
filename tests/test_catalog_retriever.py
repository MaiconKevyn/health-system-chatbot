import json
from pathlib import Path

import duckdb
import pytest

from health_system_chatbot.catalogs.duckdb_store import DuckDbCatalogStore
from health_system_chatbot.catalogs.normalization import expand_query_terms, load_domain_synonyms
from health_system_chatbot.catalogs.retriever import CatalogRetriever


def _make_catalog_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "catalog.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE cid ("
            "CID VARCHAR, DESCRICAO VARCHAR, DS_CATEGORIA VARCHAR, "
            "DS_GRUPO VARCHAR, DS_CAPITULO VARCHAR)"
        )
        con.execute(
            "INSERT INTO cid VALUES "
            "('O80', 'Parto unico espontaneo', 'Parto unico espontaneo', "
            "'O80-O84 Parto', 'XV. Gravidez, parto e puerperio'),"
            "('O82', 'Parto unico p/cesariana', 'Parto unico p/cesariana', "
            "'O80-O84 Parto', 'XV. Gravidez, parto e puerperio'),"
            "('A00', 'Colera', 'Colera', "
            "'A00-A09 Doencas infecciosas intestinais', "
            "'I. Algumas doencas infecciosas e parasitarias'),"
            "('C50', 'Neopl malig da mama', 'Neopl malig da mama', "
            "'C00-C75 Neoplasias malignas', 'II. Neoplasias tumores'),"
            "('C61', 'Neopl malig da prostata', 'Neopl malig da prostata', "
            "'C00-C75 Neoplasias malignas', 'II. Neoplasias tumores'),"
            "('Z125', 'Exame especial rastr neoplasia prostata', "
            "'Exame especial rastr de neoplasias', "
            "'Z00-Z13 Pessoas em contato servicos saude para exame investigacao', "
            "'XXI. Fatores que influenciam o estado de saude'),"
            "('J12', 'Pneumonia viral NCOP', 'Pneumonia viral NCOP', "
            "'J09-J18 Influenza gripe e pneumonia', 'X. Doencas do aparelho respiratorio'),"
            "('J18', 'Pneumonia p/microorg NE', 'Pneumonia p/microorg NE', "
            "'J09-J18 Influenza gripe e pneumonia', 'X. Doencas do aparelho respiratorio'),"
            "('J45', 'Asma', 'Asma', "
            "'J40-J47 Doencas cronicas vias aereas inferiores', "
            "'X. Doencas do aparelho respiratorio'),"
            "('G547', 'Sindr membro fantasma s/manifest dolorosa', "
            "'Transt das raizes e plexos nervosos', "
            "'G50-G59 Transtornos dos nervos raizes e plexos nervosos', "
            "'VI. Doencas do sistema nervoso')"
        )
        con.execute("CREATE TABLE procedimentos (PROC_REA VARCHAR, NOME_PROC VARCHAR)")
        con.execute(
            "INSERT INTO procedimentos VALUES "
            "('0102010366', 'CADASTRO DE SERVICOS HOSPITALARES DE ATENCAO AO PARTO E A CRIANCA'),"
            "('0211040061', 'TOCOCARDIOGRAFIA ANTE-PARTO'),"
            "('0310010039', 'PARTO NORMAL'),"
            "('0411010034', 'PARTO CESARIANO'),"
            "('0411010042', 'PARTO CESARIANO C/ LAQUEADURA TUBARIA')"
        )
        con.execute("CREATE TABLE municipios (CO_MUNICIPIO_6D INTEGER, NO_MUNICIPIO VARCHAR, SG_UF VARCHAR)")
        con.execute("INSERT INTO municipios VALUES (431490, 'Porto Alegre', 'RS')")
    finally:
        con.close()
    return db_path


def _write_procedure_concepts(project_root: Path) -> None:
    catalog_dir = project_root / "docs/domain_catalogs"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "procedure_concepts.json").write_text(
        json.dumps(
            [
                {
                    "id": "partos_total",
                    "label": "Partos realizados",
                    "description": "Procedimentos principais de parto.",
                    "scopes": ["performed_procedure", "unknown"],
                    "synonyms": ["parto", "partos", "partos aconteceram"],
                    "codes": ["0310010039", "0411010034", "0411010042"],
                    "evidence": [
                        "0310010039 PARTO NORMAL",
                        "0411010034 PARTO CESARIANO",
                        "0411010042 PARTO CESARIANO C/ LAQUEADURA TUBARIA",
                    ],
                },
                {
                    "id": "partos_cesarianos",
                    "label": "Partos cesarianos realizados",
                    "description": "Procedimentos principais de parto cesariano.",
                    "scopes": ["performed_procedure", "unknown"],
                    "synonyms": ["parto cesariano", "partos cesarianos", "cesariana"],
                    "codes": ["0411010034", "0411010042"],
                    "evidence": [
                        "0411010034 PARTO CESARIANO",
                        "0411010042 PARTO CESARIANO C/ LAQUEADURA TUBARIA",
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )


def _write_clinical_concepts(project_root: Path) -> None:
    catalog_dir = project_root / "docs/domain_catalogs"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "clinical_concepts.json").write_text(
        json.dumps(
            [
                {
                    "id": "breast_cancer",
                    "label": "Cancer de mama",
                    "description": "Neoplasia maligna da mama.",
                    "scopes": ["diagnosis", "death_cause", "unknown"],
                    "synonyms": ["cancer de mama", "neoplasia maligna da mama"],
                    "code_prefixes": ["C50"],
                    "evidence": ["OMS: Breast cancer C50"],
                },
                {
                    "id": "prostate_cancer",
                    "label": "Cancer de prostata",
                    "description": "Neoplasia maligna da prostata.",
                    "scopes": ["diagnosis", "death_cause", "unknown"],
                    "synonyms": ["cancer de prostata", "neoplasia maligna da prostata"],
                    "code_prefixes": ["C61"],
                    "evidence": ["OMS: Prostate cancer C61"],
                },
                {
                    "id": "pneumonia",
                    "label": "Pneumonia",
                    "description": "Pneumonia J12-J18.",
                    "scopes": ["diagnosis", "death_cause", "unknown"],
                    "synonyms": ["pneumonia"],
                    "code_prefixes": ["J12", "J13", "J14", "J15", "J16", "J17", "J18"],
                    "evidence": ["ICD-10: Pneumonia J12-J18"],
                },
                {
                    "id": "asthma",
                    "label": "Asma",
                    "description": "Asma J45-J46.",
                    "scopes": ["diagnosis", "death_cause", "unknown"],
                    "synonyms": ["asma"],
                    "code_prefixes": ["J45", "J46"],
                    "evidence": ["OMS: Asthma J45-J46"],
                },
            ]
        ),
        encoding="utf-8",
    )


def test_domain_synonyms_expand_query_terms(tmp_path):
    synonym_dir = tmp_path / "docs/domain_synonyms"
    synonym_dir.mkdir(parents=True)
    (synonym_dir / "clinical_terms.json").write_text(
        '{"cancer": ["neoplasia", "neopl"]}',
        encoding="utf-8",
    )

    synonyms = load_domain_synonyms(tmp_path)

    assert expand_query_terms("cancer", synonyms) == ["cancer", "neoplasia", "neopl"]


def test_retriever_rejects_unimplemented_retrieval_mode(tmp_path):
    db_path = _make_catalog_db(tmp_path)

    with pytest.raises(ValueError, match="lexical"):
        CatalogRetriever(store=DuckDbCatalogStore(db_path), retrieval_mode="vector")


def test_search_cid_prefers_group_for_diagnosis_parto(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path))

    result = retriever.search_cid("diagnostico de parto", scope="diagnosis")

    assert result.candidates
    top = result.candidates[0]
    assert top.catalog == "cid"
    assert top.level == "group"
    assert top.filter.column == "DS_GRUPO"
    assert top.filter.value == "O80-O84 Parto"
    assert top.filter.join_required is True
    assert "JOIN cid" in (top.filter.join_sql or "")


def test_search_cid_returns_chapter_for_infections(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path))

    result = retriever.search_cid("mortes por infeccoes", scope="death_cause")

    assert any(
        candidate.level == "chapter"
        and candidate.filter.column == "DS_CAPITULO"
        and "infecciosas" in str(candidate.filter.value)
        for candidate in result.candidates
    )


def test_search_cid_detects_explicit_cid_prefix(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path))

    result = retriever.search_cid("mortes por CID A", scope="death_cause")

    assert result.candidates[0].filter.table == "internacoes"
    assert result.candidates[0].filter.column == "DIAG_PRINC"
    assert result.candidates[0].filter.operator == "PREFIX"
    assert result.candidates[0].filter.value == "A%"


def test_search_cid_prefers_curated_specific_cancer_concepts(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    _write_clinical_concepts(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path), project_root=tmp_path)

    breast = retriever.search_cid("mortes por cancer de mama", scope="death_cause")
    prostate = retriever.search_cid("internacoes por cancer de prostata", scope="diagnosis")

    assert breast.candidates[0].label == "Cancer de mama"
    assert breast.candidates[0].filter.column == "DIAG_PRINC"
    assert breast.candidates[0].filter.value == "C50%"
    assert prostate.candidates[0].label == "Cancer de prostata"
    assert prostate.candidates[0].filter.value == "C61%"


def test_search_cid_prefers_curated_pneumonia_range_over_influenza_group(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    _write_clinical_concepts(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path), project_root=tmp_path)

    result = retriever.search_cid("internacoes por pneumonia", scope="diagnosis")

    top = result.candidates[0]
    assert top.label == "Pneumonia"
    assert top.filter.operator == "PREFIX_ANY"
    assert "J12%" in top.filter.value
    assert "J18%" in top.filter.value
    assert "J09" not in top.filter.where_sql_template


def test_search_cid_curated_asthma_beats_substring_false_positive(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    _write_clinical_concepts(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path), project_root=tmp_path)

    result = retriever.search_cid("asma", scope="diagnosis")

    assert result.candidates[0].label == "Asma"
    assert result.candidates[0].filter.value == ["J45%", "J46%"]


def test_search_procedures_returns_group_filter_for_matching_codes(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path))

    result = retriever.search_procedures("parto cesariano", scope="performed_procedure")

    top = result.candidates[0]
    assert top.catalog == "procedimentos"
    assert top.filter.table == "internacoes"
    assert top.filter.column == "PROC_REA"
    assert top.filter.operator == "IN"
    assert "0411010034" in top.filter.value


def test_search_procedures_prefers_curated_parto_concept(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    _write_procedure_concepts(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path), project_root=tmp_path)

    result = retriever.search_procedures("quantos partos aconteceram", scope="performed_procedure")

    top = result.candidates[0]
    assert top.label == "Partos realizados"
    assert top.filter.value == ["0310010039", "0411010034", "0411010042"]
    assert "0102010366" not in top.filter.value
    assert "0211040061" not in top.filter.value


def test_search_procedures_prefers_specific_cesarean_concept(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    _write_procedure_concepts(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path), project_root=tmp_path)

    result = retriever.search_procedures("partos cesarianos", scope="performed_procedure")

    top = result.candidates[0]
    assert top.label == "Partos cesarianos realizados"
    assert top.filter.value == ["0411010034", "0411010042"]


def test_search_dimension_values_returns_textual_value(tmp_path):
    db_path = _make_catalog_db(tmp_path)
    retriever = CatalogRetriever(store=DuckDbCatalogStore(db_path))

    result = retriever.search_dimension_values(table="municipios", query="Porto Alegre")

    assert result.candidates[0].catalog == "municipios"
    assert result.candidates[0].label == "Porto Alegre"
    assert result.candidates[0].filter.column == "NO_MUNICIPIO"
