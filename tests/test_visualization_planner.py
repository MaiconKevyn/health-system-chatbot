from health_system_chatbot.visualization.data import build_chart_planning_input
from health_system_chatbot.visualization.intent import detect_visualization_intent
from health_system_chatbot.visualization.planner import build_chart_plan, plan_chart


def test_build_chart_plan_for_temporal_metric_without_llm():
    intent = detect_visualization_intent("Gere um grafico de mortes por ano")

    plan = build_chart_plan(
        question="Gere um grafico de mortes por ano",
        intent=intent,
        allow_llm=False,
    )

    assert plan.requested is True
    assert plan.chart_type == "line"
    assert plan.x_dimension == "ano"
    assert plan.y_column == "mortes"
    assert plan.expected_result_shape == "time_metric"
    assert {"ano", "mortes"}.issubset(set(plan.required_columns))


def test_plan_chart_builds_line_spec_from_chart_plan():
    intent = detect_visualization_intent("Gere um grafico de mortes por ano")
    plan = build_chart_plan(
        question="Gere um grafico de mortes por ano",
        intent=intent,
        allow_llm=False,
    )
    chart_input = build_chart_planning_input(
        user_query="Gere um grafico de mortes por ano",
        sql_query="SELECT ano, mortes FROM resultado",
        columns=["ano", "mortes"],
        rows=[{"ano": 2021, "mortes": 10}, {"ano": 2022, "mortes": 12}],
        row_count=2,
        chart_hint=intent.chart_hint,
        chart_plan=plan,
    )

    spec = plan_chart(chart_input)

    assert spec.chartable is True
    assert spec.chart_type == "line"
    assert spec.x == "ano"
    assert spec.y == "mortes"
