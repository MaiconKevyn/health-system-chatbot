from __future__ import annotations

from dataclasses import dataclass, field

from .agent_deps import RefinerDeps
from .agents import build_sql_refiner_agent
from .config import ChatbotConfig
from .models import RetrievedContext, SqlPlan, Stage1Context, ValidationResult
from .sql_generator import _context_to_prompt, _finalize_plan
from .visualization.schema import ChartPlan


@dataclass(frozen=True)
class SqlCorrectionAttempt:
    attempt: int
    plan: SqlPlan | None
    validation: ValidationResult | None
    errors: list[str] = field(default_factory=list)


def _refinement_prompt(
    *,
    question: str,
    context: RetrievedContext,
    rejected_plan: SqlPlan,
    validation_errors: list[str],
    execution_error: str | None,
    chart_plan: ChartPlan | None = None,
) -> str:
    errors = "\n".join(f"- {error}" for error in validation_errors)
    execution = execution_error or "none"
    chart_block = (
        f"\n\nContrato visual opcional:\n{chart_plan.to_prompt_block()}"
        if chart_plan is not None and chart_plan.requested
        else ""
    )
    return (
        "Corrija a SQL rejeitada mantendo a intencao da pergunta.\n\n"
        f"Pergunta:\n{question}\n\n"
        f"Contexto recuperado:\n{_context_to_prompt(context, question)}\n\n"
        f"SQL rejeitada:\n{rejected_plan.sql}\n\n"
        f"Erros de validacao:\n{errors}\n\n"
        f"Erro de execucao:\n{execution}\n\n"
        f"{chart_block}\n\n"
        "Retorne um novo SqlPlan estruturado com SQL DuckDB read-only."
    )


def refine_sql_plan(
    *,
    question: str,
    context: RetrievedContext,
    stage1_context: Stage1Context,
    rejected_plan: SqlPlan,
    validation_errors: list[str],
    execution_error: str | None,
    config: ChatbotConfig,
    chart_plan: ChartPlan | None = None,
) -> SqlPlan:
    _ = stage1_context
    agent = build_sql_refiner_agent(config)
    deps = RefinerDeps(
        config=config,
        question=question,
        retrieved_context=context,
        rejected_plan=rejected_plan,
        validation_errors=validation_errors,
        execution_error=execution_error,
        chart_plan=chart_plan,
    )
    result = agent.run_sync(
        _refinement_prompt(
            question=question,
            context=context,
            rejected_plan=rejected_plan,
            validation_errors=validation_errors,
            execution_error=execution_error,
            chart_plan=chart_plan,
        ),
        deps=deps,
    )
    plan = result.output
    plan.source = "pydantic_ai_refiner"
    return _finalize_plan(question, plan)
