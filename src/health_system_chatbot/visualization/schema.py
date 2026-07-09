from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


ChartType = Literal["auto", "bar", "line", "area", "pie", "donut", "scatter", "kpi", "table"]
RenderableChartType = Literal["bar", "line", "area", "pie", "donut", "scatter", "kpi", "table"]
ColumnType = Literal["string", "number", "temporal", "boolean", "unknown"]
IntentSource = Literal["none", "explicit_current_query", "explicit_followup"]
WarningSeverity = Literal["info", "warning", "error"]
ExpectedResultShape = Literal[
    "single_metric",
    "category_metric",
    "time_metric",
    "time_series_metric",
    "wide_metric_comparison",
    "scatter_metric",
    "table",
    "unknown",
]


class VisualizationIntent(BaseModel):
    requested: bool = False
    source: IntentSource = "none"
    uses_last_result: bool = False
    chart_hint: ChartType = "auto"
    analysis_question: str = ""
    reason: str = ""

    @model_validator(mode="after")
    def _normalize_unrequested(self) -> "VisualizationIntent":
        if not self.requested:
            self.source = "none"
            self.uses_last_result = False
            self.chart_hint = "auto"
        return self


class ChartWarning(BaseModel):
    code: str
    message: str
    severity: WarningSeverity = "warning"


class ChartPlan(BaseModel):
    requested: bool = False
    chart_type: ChartType = "auto"
    metric: str | None = None
    x_dimension: str | None = None
    y_column: str | None = None
    series_dimension: str | None = None
    expected_result_shape: ExpectedResultShape = "unknown"
    required_columns: list[str] = Field(default_factory=list)
    sql_shape_guidance: str = ""
    reason: str = ""

    def to_prompt_block(self) -> str:
        if not self.requested:
            return "[CHART PLAN]\nrequested: false"
        return "\n".join(
            [
                "[CHART PLAN - SQL RESULT MUST SUPPORT THIS VISUALIZATION]",
                f"requested: {self.requested}",
                f"chart_type: {self.chart_type}",
                f"metric: {self.metric}",
                f"x_dimension: {self.x_dimension}",
                f"series_dimension: {self.series_dimension}",
                f"y_column: {self.y_column}",
                f"expected_result_shape: {self.expected_result_shape}",
                f"required_columns: {self.required_columns}",
                f"sql_shape_guidance: {self.sql_shape_guidance}",
            ]
        )


class ChartSqlValidation(BaseModel):
    is_valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ChartPlanningInput(BaseModel):
    user_query: str
    sql_query: str | None = None
    columns: list[str] = Field(default_factory=list)
    column_types: dict[str, ColumnType] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    chart_hint: ChartType = "auto"
    chart_plan: ChartPlan | None = None
    truncated: bool = False


class ChartSpec(BaseModel):
    chartable: bool
    chart_type: RenderableChartType = "table"
    title: str | None = None
    x: str | None = None
    y: str | None = None
    series: str | None = None
    encoding: dict[str, str] = Field(default_factory=dict)
    data: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None
    warnings: list[ChartWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_shape(self) -> "ChartSpec":
        if not self.chartable:
            return self
        if self.chart_type in {"bar", "line", "area", "pie", "donut", "scatter"}:
            if not self.x or not self.y:
                raise ValueError(f"{self.chart_type} charts require x and y")
        if self.chart_type == "kpi" and not self.y:
            raise ValueError("kpi charts require y")
        return self


class ChartPayload(BaseModel):
    requested: bool = False
    spec: ChartSpec | None = None
    echarts: dict[str, Any] | None = None
    warnings: list[ChartWarning] = Field(default_factory=list)

