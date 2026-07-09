from __future__ import annotations

from typing import Any

from .schema import ChartSpec


ECHARTS_COLORS = [
    "#2563eb",
    "#0f766e",
    "#c2410c",
    "#7c3aed",
    "#be123c",
    "#a16207",
    "#0891b2",
    "#4d7c0f",
]


def chart_spec_to_echarts_option(spec: ChartSpec | None) -> dict[str, Any] | None:
    if spec is None or not spec.chartable or spec.chart_type == "table":
        return None
    if spec.chart_type == "kpi":
        return _kpi(spec)
    if spec.chart_type in {"pie", "donut"}:
        return _pie(spec, donut=spec.chart_type == "donut")
    if spec.chart_type == "scatter":
        return _scatter(spec)
    return _cartesian(spec, area=spec.chart_type == "area")


def _base(spec: ChartSpec) -> dict[str, Any]:
    return {
        "color": ECHARTS_COLORS,
        "backgroundColor": "transparent",
        "animationDuration": 350,
        "textStyle": {"fontFamily": "Inter, system-ui, sans-serif"},
        "title": {"show": False, "text": spec.title or ""},
        "tooltip": {"trigger": "axis", "confine": True},
    }


def _cartesian(spec: ChartSpec, *, area: bool = False) -> dict[str, Any]:
    option = _base(spec)
    rows = spec.data or []
    x_values = _unique(row.get(spec.x) for row in rows)
    series_values = _unique(row.get(spec.series) for row in rows) if spec.series else [spec.y]
    chart_type = "line" if spec.chart_type == "area" else spec.chart_type
    option.update(
        {
            "grid": {"left": 56, "right": 20, "top": 24, "bottom": 48, "containLabel": True},
            "legend": {"show": bool(spec.series), "type": "scroll", "top": 0},
            "xAxis": {
                "type": "category",
                "name": spec.x or "",
                "data": x_values,
                "axisLabel": {"color": "#607067"},
            },
            "yAxis": {
                "type": "value",
                "name": spec.y or "",
                "axisLabel": {"color": "#607067"},
                "splitLine": {"lineStyle": {"color": "rgba(96,112,103,0.18)"}},
            },
            "series": [],
        }
    )
    for series_value in series_values:
        series_rows = (
            [row for row in rows if row.get(spec.series) == series_value]
            if spec.series
            else rows
        )
        values_by_x = {str(row.get(spec.x)): row.get(spec.y) for row in series_rows}
        series: dict[str, Any] = {
            "type": chart_type,
            "name": str(series_value or spec.y or "valor"),
            "data": [values_by_x.get(str(x_value), 0) for x_value in x_values],
            "emphasis": {"focus": "series"},
        }
        if chart_type == "bar":
            series["barMaxWidth"] = 34
            series["itemStyle"] = {"borderRadius": [5, 5, 0, 0]}
        if chart_type == "line":
            series["smooth"] = True
            series["symbolSize"] = 7
        if area:
            series["areaStyle"] = {"opacity": 0.16}
        option["series"].append(series)
    return option


def _pie(spec: ChartSpec, *, donut: bool) -> dict[str, Any]:
    option = _base(spec)
    option.update(
        {
            "tooltip": {"trigger": "item", "confine": True},
            "legend": {"type": "scroll", "bottom": 0},
            "series": [
                {
                    "type": "pie",
                    "name": spec.y or "valor",
                    "radius": ["42%", "68%"] if donut else ["0%", "68%"],
                    "center": ["50%", "45%"],
                    "avoidLabelOverlap": True,
                    "label": {"formatter": "{b}: {d}%"},
                    "data": [
                        {"name": str(row.get(spec.x)), "value": row.get(spec.y)}
                        for row in spec.data
                    ],
                }
            ],
        }
    )
    return option


def _scatter(spec: ChartSpec) -> dict[str, Any]:
    option = _base(spec)
    option.update(
        {
            "tooltip": {"trigger": "item", "confine": True},
            "xAxis": {"type": "value", "name": spec.x or ""},
            "yAxis": {"type": "value", "name": spec.y or ""},
            "series": [
                {
                    "type": "scatter",
                    "name": spec.y or "valor",
                    "symbolSize": 8,
                    "data": [[row.get(spec.x), row.get(spec.y)] for row in spec.data],
                }
            ],
        }
    )
    return option


def _kpi(spec: ChartSpec) -> dict[str, Any]:
    value = spec.data[0].get(spec.y) if spec.data and spec.y else None
    return {
        **_base(spec),
        "tooltip": {"show": False},
        "xAxis": {"show": False},
        "yAxis": {"show": False},
        "series": [],
        "graphic": [
            {
                "type": "text",
                "left": "center",
                "top": "middle",
                "style": {
                    "text": _format_number(value),
                    "fontSize": 34,
                    "fontWeight": 700,
                    "fill": "#1d2622",
                },
            }
        ],
    }


def _unique(values: Any) -> list[Any]:
    seen = set()
    result = []
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _format_number(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "" if value is None else str(value)

