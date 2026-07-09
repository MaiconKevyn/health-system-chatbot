from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import GroundTruthItem, Stage1Context


VariantKind = Literal["agent", "openai_baseline", "control"]


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    expected_sql: str
    difficulty: str | None = None
    expected_result_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_ground_truth(cls, item: GroundTruthItem) -> "EvalCase":
        return cls(
            id=item.id,
            question=item.question_pt,
            expected_sql=item.sql,
            difficulty=item.difficulty,
            expected_result_type=item.expected_result_type,
            metadata=item.model_dump(),
        )


@dataclass(frozen=True)
class VariantSpec:
    name: str
    kind: VariantKind
    description: str
    config_overrides: dict[str, Any] = field(default_factory=dict)
    feature_flags: dict[str, bool] = field(default_factory=dict)
    baseline_mode: str | None = None
    allow_llm: bool = True


@dataclass(frozen=True)
class SharedEvalContext:
    config: ChatbotConfig
    stage1_context: Stage1Context
    max_rows: int
    timeout_seconds: int
    numeric_tolerance: float
    cache_openai: bool = False
    cache_dir: str | None = None


class EvaluationStrategy(Protocol):
    name: str

    def run_item(
        self,
        item: GroundTruthItem,
        *,
        context: SharedEvalContext,
    ) -> dict[str, Any]:
        ...
