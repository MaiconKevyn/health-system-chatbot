from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import append_audit_record, find_related_audit_context
from .answer_synthesizer import (
    clarification_answer,
    failed_answer,
    refused_answer,
    synthesize_answer,
)
from .candidate_generation import generate_sql_candidates, should_use_multi_candidate
from .candidate_ranking import rank_sql_candidates
from .config import ChatbotConfig
from .duckdb_executor import execute_validated_sql
from .intent import classify_question
from .models import ChatbotAnswer, QuestionIntent, RetrievedContext, SqlPlan, Stage1Context
from .schema_context import retrieve_context
from .self_correction import refine_sql_plan
from .sql_generator import generate_sql_plan
from .sql_validator import validate_sql

try:
    from llama_index.core.workflow import Event, StartEvent, StopEvent, Workflow, step
except Exception:  # pragma: no cover - import fallback for partial installs
    Event = object  # type: ignore[assignment]
    StartEvent = object  # type: ignore[assignment]
    StopEvent = object  # type: ignore[assignment]
    Workflow = object  # type: ignore[assignment]

    def step(func):  # type: ignore[no-untyped-def]
        return func


class UserQuestionEvent(Event):
    question: str
    show_sql: bool = False
    show_debug: bool = False


class IntentEvent(Event):
    question: str
    show_sql: bool = False
    show_debug: bool = False
    intent: QuestionIntent


class ContextEvent(Event):
    question: str
    show_sql: bool = False
    show_debug: bool = False
    intent: QuestionIntent
    context: RetrievedContext


class SqlDraftEvent(Event):
    question: str
    show_sql: bool = False
    show_debug: bool = False
    intent: QuestionIntent
    context: RetrievedContext
    plan: SqlPlan


class FailureEvent(Event):
    message: str


def _trace_path(config: ChatbotConfig) -> Path:
    traces = config.project_root / "evaluation/chatbot/traces"
    traces.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return traces / f"trace_{stamp}.json"


def _write_trace(config: ChatbotConfig, payload: dict[str, Any]) -> None:
    path = _trace_path(config)
    payload["trace_path"] = str(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")


def _write_observability_record(
    config: ChatbotConfig,
    trace: dict[str, Any],
    *,
    write_trace: bool,
    write_audit_log: bool,
) -> None:
    if write_trace:
        _write_trace(config, trace)
    if write_audit_log:
        append_audit_record(
            config,
            {
                "event_type": "chat_question",
                "question": trace.get("question"),
                "created_at": trace.get("created_at"),
                "answer_status": trace.get("answer", {}).get("status"),
                "answer": trace.get("answer"),
                "steps": trace.get("steps", []),
                "errors": [
                    step
                    for step in trace.get("steps", [])
                    if step.get("name") in {"validation", "failure"}
                    and step.get("payload", {}).get("errors")
                ],
                "correctness": {
                    "status": "not_evaluated",
                    "reason": "Ad hoc chat questions do not have ground-truth labels by default.",
                },
                "trace_path": trace.get("trace_path"),
            },
        )


def run_chat(
    question: str,
    *,
    config: ChatbotConfig,
    stage1_context: Stage1Context,
    show_sql: bool = False,
    show_debug: bool = False,
    allow_llm: bool = True,
    write_trace: bool = True,
    write_audit_log: bool = True,
) -> ChatbotAnswer:
    trace: dict[str, Any] = {
        "question": question,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }

    intent = classify_question(question, stage1_context)
    trace["steps"].append({"name": "intent", "payload": intent.model_dump()})
    if intent.status == "needs_clarification":
        answer = clarification_answer(intent, show_debug=show_debug)
        trace["answer"] = answer.model_dump()
        _write_observability_record(
            config, trace, write_trace=write_trace, write_audit_log=write_audit_log
        )
        return answer
    if intent.status == "refused":
        answer = refused_answer(intent, show_debug=show_debug)
        trace["answer"] = answer.model_dump()
        _write_observability_record(
            config, trace, write_trace=write_trace, write_audit_log=write_audit_log
        )
        return answer

    context = retrieve_context(question, stage1_context, config=config)
    trace["steps"].append({"name": "context", "payload": context.model_dump()})
    related_context = find_related_audit_context(config, question)
    trace["steps"].append({"name": "related_context", "payload": {"items": related_context}})

    execution = None
    try:
        if should_use_multi_candidate(config, allow_llm=allow_llm):
            candidate_plans = generate_sql_candidates(
                question,
                context,
                stage1_context,
                config,
                allow_llm=allow_llm,
            )
            selection = rank_sql_candidates(
                candidate_plans,
                question=question,
                stage1_context=stage1_context,
                config=config,
            )
            trace["steps"].append(
                {"name": "sql_candidate_ranking", "payload": selection.model_dump()}
            )
            selected = selection.selected_candidate()
            if selected is not None and selected.validation is not None:
                plan = selected.plan
                validation = selected.validation
                execution = selected.execution
                trace["steps"].append({"name": "sql_plan", "payload": plan.model_dump()})
                trace["steps"].append(
                    {"name": "validation", "payload": validation.model_dump()}
                )
                if execution is not None:
                    trace["steps"].append(
                        {"name": "execution", "payload": execution.model_dump()}
                    )
            else:
                fallback = selection.best_candidate()
                if fallback is None:
                    raise RuntimeError("No SQL candidates were generated.")
                plan = fallback.plan
                validation = fallback.validation or validate_sql(
                    plan.sql,
                    stage1_context,
                    question=question,
                    plan=plan,
                )
                trace["steps"].append({"name": "sql_plan", "payload": plan.model_dump()})
                trace["steps"].append(
                    {"name": "validation", "payload": validation.model_dump()}
                )
        else:
            plan = generate_sql_plan(
                question,
                context,
                stage1_context,
                config,
                allow_llm=allow_llm,
            )
            trace["steps"].append({"name": "sql_plan", "payload": plan.model_dump()})
            validation = validate_sql(plan.sql, stage1_context, question=question, plan=plan)
            trace["steps"].append({"name": "validation", "payload": validation.model_dump()})
    except Exception as exc:
        answer = failed_answer(str(exc), show_debug=show_debug)
        trace["answer"] = answer.model_dump()
        trace["steps"].append({"name": "failure", "payload": {"errors": [str(exc)]}})
        _write_observability_record(
            config, trace, write_trace=write_trace, write_audit_log=write_audit_log
        )
        return answer

    if (
        not validation.is_valid
        and allow_llm
        and config.agent_framework == "pydantic_ai"
        and config.sql_correction_attempts > 0
    ):
        for attempt in range(1, config.sql_correction_attempts + 1):
            try:
                corrected_plan = refine_sql_plan(
                    question=question,
                    context=context,
                    stage1_context=stage1_context,
                    rejected_plan=plan,
                    validation_errors=validation.errors,
                    execution_error=None,
                    config=config,
                )
                corrected_validation = validate_sql(
                    corrected_plan.sql,
                    stage1_context,
                    question=question,
                    plan=corrected_plan,
                )
                trace["steps"].append(
                    {
                        "name": "sql_correction",
                        "payload": {
                            "attempt": attempt,
                            "plan": corrected_plan.model_dump(),
                            "validation": corrected_validation.model_dump(),
                        },
                    }
                )
                plan = corrected_plan
                validation = corrected_validation
                if validation.is_valid:
                    break
            except Exception as exc:
                trace["steps"].append(
                    {
                        "name": "sql_correction",
                        "payload": {
                            "attempt": attempt,
                            "errors": [str(exc)],
                        },
                    }
                )
                break
    if not validation.is_valid:
        answer = failed_answer("; ".join(validation.errors), show_debug=show_debug)
        trace["answer"] = answer.model_dump()
        _write_observability_record(
            config, trace, write_trace=write_trace, write_audit_log=write_audit_log
        )
        return answer

    execution_error: str | None = None
    if execution is None:
        try:
            execution = execute_validated_sql(
                validation,
                db_path=config.db_path,
                max_rows=config.max_rows,
            )
            trace["steps"].append({"name": "execution", "payload": execution.model_dump()})
        except Exception as exc:
            execution_error = str(exc)

    if (
        execution is None
        and execution_error
        and allow_llm
        and config.agent_framework == "pydantic_ai"
        and config.sql_correction_attempts > 0
    ):
        for attempt in range(1, config.sql_correction_attempts + 1):
            try:
                corrected_plan = refine_sql_plan(
                    question=question,
                    context=context,
                    stage1_context=stage1_context,
                    rejected_plan=plan,
                    validation_errors=[],
                    execution_error=execution_error,
                    config=config,
                )
                corrected_validation = validate_sql(
                    corrected_plan.sql,
                    stage1_context,
                    question=question,
                    plan=corrected_plan,
                )
                trace["steps"].append(
                    {
                        "name": "execution_correction",
                        "payload": {
                            "attempt": attempt,
                            "execution_error": execution_error,
                            "plan": corrected_plan.model_dump(),
                            "validation": corrected_validation.model_dump(),
                        },
                    }
                )
                plan = corrected_plan
                validation = corrected_validation
                if not validation.is_valid:
                    execution_error = "; ".join(validation.errors)
                    continue
                try:
                    execution = execute_validated_sql(
                        validation,
                        db_path=config.db_path,
                        max_rows=config.max_rows,
                    )
                    trace["steps"].append(
                        {"name": "execution", "payload": execution.model_dump()}
                    )
                    execution_error = None
                    break
                except Exception as corrected_exc:
                    execution_error = str(corrected_exc)
            except Exception as correction_exc:
                execution_error = str(correction_exc)
                trace["steps"].append(
                    {
                        "name": "execution_correction",
                        "payload": {
                            "attempt": attempt,
                            "errors": [execution_error],
                        },
                    }
                )
                break

    if execution is None:
        answer = failed_answer(execution_error or "SQL execution failed", show_debug=show_debug)
        trace["answer"] = answer.model_dump()
        trace["steps"].append(
            {"name": "failure", "payload": {"errors": [execution_error or "SQL execution failed"]}}
        )
        _write_observability_record(
            config, trace, write_trace=write_trace, write_audit_log=write_audit_log
        )
        return answer

    answer = synthesize_answer(
        question=question,
        intent=intent,
        plan=plan,
        validation=validation,
        execution=execution,
        context=context,
        related_context=related_context,
        show_sql=show_sql,
        show_debug=show_debug,
        config=config,
        allow_llm=allow_llm,
    )
    trace["answer"] = answer.model_dump()
    _write_observability_record(
        config, trace, write_trace=write_trace, write_audit_log=write_audit_log
    )
    return answer


class LlamaIndexChatWorkflow(Workflow):
    """LlamaIndex Workflow wrapper around the deterministic chatbot pipeline."""

    def __init__(self, *, config: ChatbotConfig, stage1_context: Stage1Context, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config = config
        self.stage1_context = stage1_context

    @step
    async def start(self, ev: StartEvent) -> StopEvent:
        question = getattr(ev, "question", "")
        show_sql = bool(getattr(ev, "show_sql", False))
        show_debug = bool(getattr(ev, "show_debug", False))
        answer = run_chat(
            question,
            config=self.config,
            stage1_context=self.stage1_context,
            show_sql=show_sql,
            show_debug=show_debug,
        )
        return StopEvent(result=answer)
