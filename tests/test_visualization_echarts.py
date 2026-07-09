from health_system_chatbot.visualization.echarts import chart_spec_to_echarts_option
from health_system_chatbot.visualization.renderer_contract import build_chart_payload
from health_system_chatbot.visualization.schema import ChartSpec


def test_line_chart_spec_converts_to_echarts_option():
    spec = ChartSpec(
        chartable=True,
        chart_type="line",
        x="ano",
        y="mortes",
        data=[{"ano": 2021, "mortes": 10}, {"ano": 2022, "mortes": 12}],
    )

    option = chart_spec_to_echarts_option(spec)

    assert option is not None
    assert option["xAxis"]["data"] == [2021, 2022]
    assert option["series"][0]["type"] == "line"
    assert option["series"][0]["data"] == [10, 12]


def test_chart_payload_includes_echarts_for_chartable_spec():
    spec = ChartSpec(
        chartable=True,
        chart_type="bar",
        x="sexo",
        y="internacoes",
        data=[{"sexo": "Feminino", "internacoes": 7}],
    )

    payload = build_chart_payload(requested=True, spec=spec)

    assert payload is not None
    assert payload.requested is True
    assert payload.echarts is not None
    assert payload.spec is spec
