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


def test_annual_deliveries_chart_uses_year_without_llm():
    question = "Me mostre em um gráfico a quantidade de partos espontâneo cefálico anuais feitos no Rio Grande do Sul"
    plan = build_chart_plan(question=question, intent=detect_visualization_intent(question), allow_llm=False)

    assert (plan.chart_type, plan.x_dimension, plan.expected_result_shape) == ("line", "ano", "time_metric")
    assert plan.metric == "Partos espontâneos cefálicos"


def test_chart_title_preserves_named_subtype_with_generic_count_alias():
    question = (
        "Demonstre em um gráfico a quantidade de partos espontâneo cefálico "
        "anuais feitos no rio grande do sul"
    )
    chart_input = build_chart_planning_input(
        user_query=question,
        sql_query=None,
        columns=["ano", "quantidade"],
        rows=[{"ano": 2025, "quantidade": 24611}],
        row_count=1,
        chart_plan={
            "requested": True,
            "chart_type": "line",
            "metric": "Quantidade de partos espontâneos cefálicos",
            "x_dimension": "ano",
            "y_column": "quantidade",
        },
    )
    spec = plan_chart(chart_input)
    assert spec.title == "Quantidade de partos espontâneos cefálicos por ano"
    assert spec.y == "quantidade"

    # When the requested measure is absent the chart uses the actual result.
    chart_input.chart_plan.y_column = "custo"
    assert plan_chart(chart_input).title == "quantidade por ano"


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


def test_llm_chart_plan_drops_source_columns_from_required_columns():
    # The chart-plan model listed source/filter columns as required; the chart
    # contract correction then grouped by them and broke the yearly totals.
    from health_system_chatbot.visualization.planner import _normalize_chart_plan
    from health_system_chatbot.visualization.schema import ChartPlan

    question = "Me mostre em um gráfico a quantidade de partos espontâneo cefálico anuais feitos no Rio Grande do Sul"
    llm_plan = ChartPlan(
        requested=True,
        chart_type="line",
        x_dimension="ano",
        y_column="quantidade_partos",
        expected_result_shape="time_metric",
        required_columns=[
            "internacao.DT_INTER",
            "internacao_procedimento.PROC_REA",
            "procedimentos.NOME_PROC",
            "hospital.MUNIC_MOV",
            "municipios.SG_UF",
        ],
    )

    plan = _normalize_chart_plan(llm_plan, question=question, intent=detect_visualization_intent(question))

    assert plan.required_columns == ["ano", "quantidade_partos"]
