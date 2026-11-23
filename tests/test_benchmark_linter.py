from health_system_chatbot.models import GroundTruthItem
from evaluation.chatbot.benchmark_linter import lint_benchmark_item


def test_linter_finds_limit_not_present_in_question():
    item = GroundTruthItem(
        id="SYNTHETIC",
        question_pt="Quais municípios tiveram crescimento?",
        sql="SELECT municipio FROM x ORDER BY total DESC LIMIT 10",
    )

    issues = lint_benchmark_item(item)

    assert {issue.code for issue in issues} == {"hidden_limit"}


def test_linter_accepts_explicit_limit_and_support():
    item = GroundTruthItem(
        id="SYNTHETIC",
        question_pt="Quais são os 5 hospitais com mais de 100 internações?",
        sql=(
            "SELECT hospital, COUNT(*) AS n FROM x GROUP BY hospital "
            "HAVING COUNT(*) > 100 ORDER BY n DESC LIMIT 5"
        ),
    )

    issues = lint_benchmark_item(item)

    assert not {"hidden_limit", "hidden_minimum_support"} & {
        issue.code for issue in issues
    }


def test_linter_finds_hidden_partition():
    item = GroundTruthItem(
        id="SYNTHETIC",
        question_pt="Quais são os 3 hospitais nos estados selecionados?",
        sql=(
            "SELECT * FROM (SELECT hospital, ROW_NUMBER() OVER "
            "(PARTITION BY estado ORDER BY n DESC) AS rn FROM x) WHERE rn <= 3"
        ),
    )

    assert "hidden_partition" in {issue.code for issue in lint_benchmark_item(item)}


def test_linter_accepts_intermediate_years_in_explicit_range():
    item = GroundTruthItem(
        id="SYNTHETIC",
        question_pt="Quais entidades cresceram de 2019 a 2021?",
        sql=(
            "SELECT * FROM x WHERE ano BETWEEN 2019 AND 2021 "
            "AND total_2020 > total_2019 AND total_2021 > total_2020"
        ),
    )

    assert "hidden_time_window" not in {
        issue.code for issue in lint_benchmark_item(item)
    }


def test_linter_does_not_treat_count_positive_as_support_threshold():
    item = GroundTruthItem(
        id="SYNTHETIC",
        question_pt="Compare as médias entre os grupos com dados.",
        sql="SELECT grupo, AVG(valor) FROM x GROUP BY grupo HAVING COUNT(*) > 0",
    )

    assert "hidden_minimum_support" not in {
        issue.code for issue in lint_benchmark_item(item)
    }
