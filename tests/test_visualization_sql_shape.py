from health_system_chatbot.visualization.schema import ChartPlan
from health_system_chatbot.visualization.sql_shape import validate_sql_against_chart_plan


def test_chart_sql_validation_accepts_required_output_columns():
    plan = ChartPlan(
        requested=True,
        chart_type="bar",
        x_dimension="sexo",
        y_column="internacoes",
        expected_result_shape="category_metric",
        required_columns=["sexo", "internacoes"],
    )

    validation = validate_sql_against_chart_plan(
        plan,
        """
        SELECT s.DESCRICAO AS sexo, COUNT(*) AS internacoes
        FROM internacoes i
        JOIN sexo s ON i.SEXO = s.SEXO
        GROUP BY 1
        """,
    )

    assert validation.is_valid is True
    assert validation.errors == []


def test_chart_sql_validation_warns_for_raw_sex_code():
    plan = ChartPlan(
        requested=True,
        chart_type="bar",
        x_dimension="sexo",
        y_column="internacoes",
        expected_result_shape="category_metric",
        required_columns=["sexo", "internacoes"],
    )

    validation = validate_sql_against_chart_plan(
        plan,
        "SELECT SEXO AS sexo, COUNT(*) AS internacoes FROM internacoes GROUP BY 1",
    )

    assert validation.is_valid is True
    assert "human-readable labels" in validation.warnings[0]


def test_chart_sql_validation_reports_missing_required_metric():
    plan = ChartPlan(
        requested=True,
        chart_type="line",
        x_dimension="ano",
        y_column="mortes",
        expected_result_shape="time_metric",
        required_columns=["ano", "mortes"],
    )

    validation = validate_sql_against_chart_plan(
        plan,
        "SELECT year(DT_INTER) AS ano, COUNT(*) AS internacoes FROM internacoes GROUP BY 1",
    )

    assert validation.is_valid is False
    assert validation.errors == ["SQL does not output chart required column: mortes"]
