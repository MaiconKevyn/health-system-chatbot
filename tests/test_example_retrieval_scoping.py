from health_system_chatbot.artifacts import load_stage1_context
from health_system_chatbot.context_retrieval import rank_query_examples
from health_system_chatbot.question_contract import build_question_contract


def test_age_band_example_requires_explicit_age_definition():
    ctx = load_stage1_context()
    question = "Quais procedimentos são mais frequentes por faixa etária?"
    selected, decisions = rank_query_examples(
        question,
        ctx,
        contract=build_question_contract(question),
    )

    assert "EX001" not in {item.id for item in selected}
    decision = next(item for item in decisions if item.example_id == "EX001")
    assert "requires_explicit:dimensions.age_band.definition" in decision.rejection_reasons


def test_uti_usage_example_is_forbidden_for_positive_cost():
    ctx = load_stage1_context()
    question = "Qual o custo médio de UTI por hospital?"
    selected, decisions = rank_query_examples(
        question,
        ctx,
        contract=build_question_contract(question),
    )

    assert "EX007" not in {item.id for item in selected}
    decision = next(item for item in decisions if item.example_id == "EX007")
    assert any(reason.startswith("forbidden_transfer") for reason in decision.rejection_reasons)


def test_indigenous_example_is_retrieved_by_concept():
    ctx = load_stage1_context()
    question = "Quais procedimentos aparecem em internações de indígenas?"
    selected, _ = rank_query_examples(
        question,
        ctx,
        contract=build_question_contract(question),
        retrieved_tables=["internacoes", "procedimentos", "raca_cor"],
    )

    assert "EX004" in {item.id for item in selected}


def test_hidden_limit_example_no_longer_contains_limit():
    ctx = load_stage1_context()
    example = next(item for item in ctx.example_bank if item.id == "EX012")

    assert "LIMIT" not in example.sql.upper()
    assert "nao aplique limit" in example.data_quality_notes.lower()


def test_retrieval_decisions_explain_acceptance_and_rejection():
    ctx = load_stage1_context()
    selected, decisions = rank_query_examples(
        "Quais são os 3 hospitais com mais de 300 internações?",
        ctx,
        retrieved_tables=["internacoes"],
    )

    assert selected
    assert all(item.reasons or item.rejection_reasons for item in decisions)
    assert {item.example_id for item in decisions} == {item.id for item in ctx.example_bank}
