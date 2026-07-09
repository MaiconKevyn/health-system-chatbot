from health_system_chatbot.intent import classify_question


def test_ambiguous_cost_location_requires_clarification():
    intent = classify_question("Qual foi o custo por local?")

    assert intent.status == "needs_clarification"
    assert intent.ambiguities


def test_patient_unique_is_refused_without_reliable_identifier():
    intent = classify_question("Quantos pacientes unicos existem na base?")

    assert intent.status == "refused"


def test_basic_admission_count_is_answerable():
    intent = classify_question("Quantas internacoes existem?")

    assert intent.status == "answerable"


def test_ambiguous_contraceptive_requires_clarification():
    intent = classify_question("Como as internacoes se distribuem por contraceptivo informado?")

    assert intent.status == "needs_clarification"
    assert any("CONTRACEP1" in ambiguity for ambiguity in intent.ambiguities)


def test_contraceptive_catalog_question_is_answerable():
    intent = classify_question("Quantos tipos de contraceptivos existem no catalogo?")

    assert intent.status == "answerable"


def test_contraceptive_1_column_alias_is_answerable():
    intent = classify_question(
        "Como as internacoes com contraceptivo 1 informado se distribuem por tipo de contraceptivo?"
    )

    assert intent.status == "answerable"
