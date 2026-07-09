from __future__ import annotations

from .echarts import chart_spec_to_echarts_option
from .schema import ChartPayload, ChartSpec


def build_chart_payload(*, requested: bool, spec: ChartSpec | None) -> ChartPayload | None:
    if not requested:
        return None
    warnings = spec.warnings if spec else []
    return ChartPayload(
        requested=True,
        spec=spec,
        echarts=chart_spec_to_echarts_option(spec),
        warnings=warnings,
    )
