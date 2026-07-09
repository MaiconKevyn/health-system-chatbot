from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


CatalogName = Literal["cid", "procedimentos", "municipios", "dimension"]
CatalogLevel = Literal["chapter", "group", "category", "code", "value"]
FilterOperator = Literal["=", "IN", "LIKE", "PREFIX", "PREFIX_ANY", "RANGE"]


class CatalogFilter(BaseModel):
    table: str
    column: str
    operator: FilterOperator
    value: Any
    join_required: bool = False
    join_sql: str | None = None
    where_sql_template: str


class CatalogCandidate(BaseModel):
    catalog: CatalogName
    level: CatalogLevel
    code: str | None = None
    label: str
    description: str = ""
    source_table: str
    source_column: str
    filter: CatalogFilter
    evidence: list[str] = Field(default_factory=list)
    score: float = 0.0
    confidence: Literal["low", "medium", "high"] = "medium"
    ambiguity_notes: list[str] = Field(default_factory=list)


class CatalogSearchResult(BaseModel):
    query: str
    catalog: CatalogName
    candidates: list[CatalogCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CatalogDecision(BaseModel):
    catalog: str
    query: str
    selected_candidate_label: str
    selected_filter: str
    confidence: str = "medium"
    alternatives: list[str] = Field(default_factory=list)


class CatalogToolCall(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: CatalogSearchResult | None = None
    error: str | None = None
