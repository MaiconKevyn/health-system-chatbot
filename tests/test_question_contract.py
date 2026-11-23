from health_system_chatbot.question_contract import build_question_contract


def test_contract_leaves_unspecified_age_bands_unresolved():
    contract = build_question_contract(
        "Qual a taxa de mortalidade por faixa etaria?"
    )

    assert "age_band_definition_unresolved" in contract.ambiguities
    assert any(d.concept == "age_band" for d in contract.dimensions)


def test_contract_extracts_explicit_ranking_partition_and_support():
    contract = build_question_contract(
        "Quais são os 5 hospitais por estado com mais de 500 internações?"
    )

    assert contract.intent == "ranking"
    assert contract.ranking.n == 5
    assert contract.ranking.partition_by == ["state"]
    assert contract.ranking.minimum_support == 500
    assert contract.ranking.explicit_n
    assert contract.ranking.explicit_minimum_support


def test_states_in_scope_do_not_imply_partition_by_state():
    contract = build_question_contract(
        "Quais hospitais nos estados MA e RS tiveram mais internações?"
    )

    assert "state" not in contract.ranking.partition_by


def test_temporal_basis_is_unresolved_when_question_only_mentions_year():
    contract = build_question_contract(
        "Qual a taxa anual de mortalidade em 2021?"
    )

    assert contract.time.grain == "year"
    assert contract.time.basis == "unresolved"
    assert "date_basis_unresolved" in contract.ambiguities


def test_hospitalization_occurring_in_period_uses_admission_date():
    contract = build_question_contract(
        "Quantas internações ocorreram por ano entre 2019 e 2021?"
    )

    assert contract.time.basis == "admission_date"
    assert "date_basis_unresolved" not in contract.ambiguities


def test_age_in_years_does_not_imply_yearly_grain():
    questions = (
        "Quantas internações de pacientes com mais de 60 anos houve no RS?",
        "Quantas internacoes foram de criancas de 1 a 4 anos?",
        "Existem idades fora do intervalo aceito de 0 a 150 anos?",
        "Quantas internações houve nos últimos 5 anos?",
    )

    for question in questions:
        contract = build_question_contract(question)
        assert contract.time.grain == "none", question
        assert "date_basis_unresolved" not in contract.ambiguities, question


def test_years_as_period_still_imply_yearly_grain():
    contract = build_question_contract(
        "Quantas mulheres acima de 50 anos morreram por cancer ao longo dos anos?"
    )

    assert contract.time.grain == "year"


def test_anos_only_matches_as_a_whole_word():
    contract = build_question_contract("Quantas internações foram causadas por danos hepáticos?")

    assert contract.time.grain == "none"


def test_required_socioeconomic_source_is_explicit():
    contract = build_question_contract(
        "Quais municípios têm maior taxa por mil habitantes?"
    )

    assert contract.required_sources == ["socioeconomico"]


def test_singular_superlative_means_explicit_top_one():
    contract = build_question_contract(
        "Em qual combinação de estado e ano ocorreu a maior taxa?"
    )

    assert contract.ranking.n == 1
    assert contract.ranking.explicit_n


def test_explicit_age_cohorts_partition_a_ranking():
    contract = build_question_contract(
        "Quais são os 10 principais diagnósticos para menores de 18, entre 18 e 64 e acima de 64 anos?"
    )

    assert contract.ranking.partition_by == ["age_band"]


def test_unapproved_clinical_definitions_remain_explicitly_unresolved():
    obstetric = build_question_contract("Qual o total de internações obstétricas?")
    secondary = build_question_contract(
        "Qual percentual possui diagnóstico secundário preenchido?"
    )

    assert "obstetric_population_definition_unresolved" in obstetric.ambiguities
    assert "secondary_diagnosis_definition_unresolved" in secondary.ambiguities
