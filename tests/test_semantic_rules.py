from health_system_chatbot.artifacts import load_stage1_context
from health_system_chatbot.question_contract import build_question_contract
from health_system_chatbot.semantic_rules import applicable_semantic_rules


def test_uti_usage_rule_does_not_transfer_to_cost():
    ctx = load_stage1_context()

    usage = applicable_semantic_rules(
        build_question_contract("Qual a taxa de uso de UTI?"),
        ctx.semantic_rules,
    )
    cost = applicable_semantic_rules(
        build_question_contract("Qual o custo médio de UTI?"),
        ctx.semantic_rules,
    )

    assert {rule.id for rule in usage} == {"uti_usage_v1"}
    assert {rule.id for rule in cost} == {"positive_uti_cost_v1"}


def test_indigenous_rule_has_database_provenance_and_negative_tests():
    ctx = load_stage1_context()
    rule = next(rule for rule in ctx.semantic_rules if rule.id == "indigenous_population_v1")

    assert rule.provenance.type == "database_dimension"
    assert len(rule.negative_test_cases) >= 2
    assert "ETNIA" in " ".join(rule.negative_test_cases)


def test_covid_rule_is_catalog_backed_and_requires_both_catalog_codes():
    ctx = load_stage1_context()
    rules = applicable_semantic_rules(
        build_question_contract("Qual o total de internações por COVID ou coronavírus?"),
        ctx.semantic_rules,
    )

    rule = next(rule for rule in rules if rule.id == "covid_admissions_v1")
    assert rule.provenance.type == "database_catalog"
    assert rule.required_sql_all == ["B342", "B972"]
    assert len(rule.negative_test_cases) >= 2
