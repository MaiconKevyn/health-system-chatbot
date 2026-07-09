from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .config import ChatbotConfig
from .models import ExecutionResult, RetrievedContext, SqlPlan, Stage1Context, ValidationResult

if TYPE_CHECKING:
    from .catalogs.retriever import CatalogRetriever
    from .visualization.schema import ChartPlan, VisualizationIntent


@dataclass(frozen=True)
class ChatDeps:
    config: ChatbotConfig
    stage1_context: Stage1Context
    retrieved_context: RetrievedContext
    catalog_retriever: "CatalogRetriever | None" = None
    related_context: list[dict[str, Any]] = field(default_factory=list)
    chart_plan: "ChartPlan | None" = None


@dataclass(frozen=True)
class ChartDeps:
    config: ChatbotConfig
    question: str
    visualization_intent: "VisualizationIntent"
    retrieved_context: RetrievedContext | None = None


@dataclass(frozen=True)
class AnswerDeps:
    config: ChatbotConfig
    question: str
    plan: SqlPlan
    validation: ValidationResult
    execution: ExecutionResult
    caveats: list[str] = field(default_factory=list)
    related_context: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RefinerDeps:
    config: ChatbotConfig
    question: str
    retrieved_context: RetrievedContext
    rejected_plan: SqlPlan
    catalog_retriever: "CatalogRetriever | None" = None
    chart_plan: "ChartPlan | None" = None
    validation_errors: list[str] = field(default_factory=list)
    execution_error: str | None = None
