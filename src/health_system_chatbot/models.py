from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


IntentStatus = Literal["answerable", "needs_clarification", "refused"]
AnswerStatus = Literal["answered", "clarified", "refused", "failed"]
ValidationSeverity = Literal["info", "warning", "error"]
Grain = Literal[
    "hospitalization",
    "procedure_occurrence",
    "municipality_year",
    "hospital",
    "other",
]
GeographyBasis = Literal["residence", "hospital", "none", "mixed"]


class QuestionIntent(BaseModel):
    status: IntentStatus
    reason: str
    normalized_question: str
    ambiguities: list[str] = Field(default_factory=list)
    required_caveats: list[str] = Field(default_factory=list)


class JoinPolicy(BaseModel):
    left: str
    right: str
    business_meaning: str = ""
    left_rows: int | None = None
    matched_rows: int | None = None
    unmatched_rows: int | None = None
    match_rate_non_null: float | None = None
    confidence: str = ""
    accepted_usage_policy: str = ""


class GroundTruthItem(BaseModel):
    id: str
    question_pt: str
    sql: str
    difficulty: str | None = None
    tables_used: list[str] = Field(default_factory=list)
    columns_used: list[str] = Field(default_factory=list)
    expected_result_type: str | None = None
    result_summary: str | None = None
    validation_evidence: str | None = None
    assumptions: str | None = None
    data_quality_notes: str | None = None
    semantic_disposition: str | None = None


class BusinessMetric(BaseModel):
    name: str
    description: str
    formula: str = ""
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    trigger_terms: list[str] = Field(default_factory=list)


class ValueHint(BaseModel):
    table: str
    column: str
    value: Any
    label: str = ""
    match_reason: str = ""


class TableContext(BaseModel):
    table_name: str
    schema_name: str = "main"
    column_count: int | None = None
    estimated_size: int | None = None
    columns: list[str] = Field(default_factory=list)
    column_types: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class Stage1Context(BaseModel):
    project_root: str
    tables: dict[str, TableContext] = Field(default_factory=dict)
    join_policies: list[JoinPolicy] = Field(default_factory=list)
    ground_truth: list[GroundTruthItem] = Field(default_factory=list)
    readiness_notes: str = ""
    business_dictionary: str = ""
    schema_catalog: str = ""
    relationship_map: str = ""
    data_quality_report: str = ""

    @property
    def table_names(self) -> set[str]:
        return set(self.tables)


class RetrievedContext(BaseModel):
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    table_context: list[str] = Field(default_factory=list)
    join_policies: list[JoinPolicy] = Field(default_factory=list)
    business_metrics: list[BusinessMetric] = Field(default_factory=list)
    value_hints: list[ValueHint] = Field(default_factory=list)
    query_examples: list[GroundTruthItem] = Field(default_factory=list)
    data_quality_caveats: list[str] = Field(default_factory=list)
    retrieval_mode: str = "schema"


class SqlPlan(BaseModel):
    question: str
    sql: str
    tables_used: list[str] = Field(default_factory=list)
    columns_used: list[str] = Field(default_factory=list)
    metric_basis: list[str] = Field(default_factory=list)
    grain: Grain = "other"
    date_basis: str = "unknown"
    geography_basis: GeographyBasis = "none"
    join_assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    source: str = "llm"


class ValidationResult(BaseModel):
    is_valid: bool
    severity: ValidationSeverity
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    required_clarification: str | None = None
    safe_sql: str | None = None


class ExecutionResult(BaseModel):
    sql: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    elapsed_seconds: float = 0.0
    result_hash: str = ""
    truncated: bool = False


class ChatbotAnswer(BaseModel):
    answer_pt: str
    sql: str = ""
    result_summary: str = ""
    caveats: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    developer_context: dict[str, Any] = Field(default_factory=dict)
    status: AnswerStatus


class EvaluationRecord(BaseModel):
    id: str
    question_pt: str
    difficulty: str | None = None
    status: AnswerStatus
    intent_status: IntentStatus
    sql_valid: bool
    executed: bool
    result_match: bool | None = None
    latency_seconds: float = 0.0
    error_category: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
