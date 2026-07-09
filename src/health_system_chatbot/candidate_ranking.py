from __future__ import annotations

from pydantic import BaseModel, Field

from .config import ChatbotConfig
from .duckdb_executor import execute_validated_sql
from .models import ExecutionResult, SqlPlan, Stage1Context, ValidationResult
from .sql_validator import validate_sql
from .visualization.schema import ChartPlan
from .visualization.sql_shape import validate_sql_against_chart_plan


class RankedSqlCandidate(BaseModel):
    candidate_id: str
    plan: SqlPlan
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    score: float = 0.0
    rank_reason: str = ""
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SqlCandidateSelection(BaseModel):
    selected_candidate_id: str | None = None
    candidates: list[RankedSqlCandidate] = Field(default_factory=list)
    selection_reason: str = ""

    def selected_candidate(self) -> RankedSqlCandidate | None:
        if self.selected_candidate_id is None:
            return None
        for candidate in self.candidates:
            if candidate.candidate_id == self.selected_candidate_id:
                return candidate
        return None

    def best_candidate(self) -> RankedSqlCandidate | None:
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda candidate: candidate.score)


def _score_candidate(
    validation: ValidationResult,
    execution: ExecutionResult | None,
    errors: list[str],
) -> tuple[float, str]:
    if not validation.is_valid:
        return -100.0 - len(validation.errors), "invalid_sql"
    if execution is None:
        return -20.0 - len(errors), "execution_failed"

    score = 100.0
    score -= len(validation.warnings) * 2
    score -= len(errors) * 3
    if execution.row_count > 0:
        score += 10.0
    if execution.truncated:
        score -= 3.0
    score -= min(execution.elapsed_seconds, 10.0)
    return score, "validated_and_executed"


def rank_sql_candidates(
    candidates: list[SqlPlan],
    *,
    question: str,
    stage1_context: Stage1Context,
    config: ChatbotConfig,
    chart_plan: ChartPlan | None = None,
) -> SqlCandidateSelection:
    ranked: list[RankedSqlCandidate] = []

    for index, plan in enumerate(candidates, start=1):
        candidate_id = f"candidate_{index}"
        validation = validate_sql(plan.sql, stage1_context, question=question, plan=plan)
        execution: ExecutionResult | None = None
        errors = list(validation.errors)
        warnings = list(validation.warnings)
        if chart_plan is not None and chart_plan.requested:
            chart_validation = validate_sql_against_chart_plan(chart_plan, plan.sql)
            errors.extend(f"chart: {error}" for error in chart_validation.errors)
            warnings.extend(f"chart: {warning}" for warning in chart_validation.warnings)
            validation = validation.model_copy(update={"warnings": warnings})

        if validation.is_valid:
            try:
                execution = execute_validated_sql(
                    validation,
                    db_path=config.db_path,
                    max_rows=config.max_rows,
                )
            except Exception as exc:
                errors.append(str(exc))

        score, rank_reason = _score_candidate(validation, execution, errors)
        ranked.append(
            RankedSqlCandidate(
                candidate_id=candidate_id,
                plan=plan,
                validation=validation,
                execution=execution,
                score=score,
                rank_reason=rank_reason,
                errors=errors,
                warnings=warnings,
            )
        )

    executable = [candidate for candidate in ranked if candidate.execution is not None]
    if not executable:
        return SqlCandidateSelection(
            selected_candidate_id=None,
            candidates=ranked,
            selection_reason="No candidate validated and executed successfully.",
        )

    selected = max(executable, key=lambda candidate: candidate.score)
    return SqlCandidateSelection(
        selected_candidate_id=selected.candidate_id,
        candidates=ranked,
        selection_reason=(
            f"Selected {selected.candidate_id}: {selected.rank_reason}, "
            f"score={selected.score:.3f}."
        ),
    )
