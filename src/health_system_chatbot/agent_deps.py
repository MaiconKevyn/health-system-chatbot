from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import ChatbotConfig
from .models import ExecutionResult, RetrievedContext, SqlPlan, Stage1Context, ValidationResult


@dataclass(frozen=True)
class ChatDeps:
    config: ChatbotConfig
    stage1_context: Stage1Context
    retrieved_context: RetrievedContext
    related_context: list[dict[str, Any]] = field(default_factory=list)


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
    validation_errors: list[str] = field(default_factory=list)
    execution_error: str | None = None

