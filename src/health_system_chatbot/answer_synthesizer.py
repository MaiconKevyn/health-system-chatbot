from __future__ import annotations

import json
import re
from typing import Any

from llama_index.core import PromptTemplate
from pydantic import BaseModel

from .agent_deps import AnswerDeps
from .agents import build_answer_agent
from .config import ChatbotConfig
from .llm import build_openai_llm
from .models import (
    ChatbotAnswer,
    ExecutionResult,
    QuestionIntent,
    RetrievedContext,
    SqlPlan,
    ValidationResult,
)
from .prompts import NATURAL_ANSWER_PROMPT
from .text import normalize_text
from .visualization.schema import ChartPayload, ChartPlan


class NaturalAnswer(BaseModel):
    answer_pt: str


NATURAL_ANSWER_ROW_LIMIT = 50


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def _format_field_value(key: str, value: object) -> str:
    if "ano" in key.lower() and isinstance(value, int):
        return str(value)
    return _format_value(value)


def _summarize_result(result: ExecutionResult) -> str:
    if not result.rows:
        return "A consulta executou, mas nao retornou linhas."
    if len(result.rows) == 1:
        row = result.rows[0]
        return ", ".join(f"{key}={_format_field_value(key, value)}" for key, value in row.items())
    first = result.rows[0]
    preview = ", ".join(f"{key}={_format_field_value(key, value)}" for key, value in first.items())
    count_key = _count_column(first)
    total = None
    if count_key and all(isinstance(row.get(count_key), int | float) for row in result.rows):
        total = sum(row[count_key] for row in result.rows)
    total_summary = (
        f" Soma de {count_key} nas linhas retornadas: {_format_value(total)}."
        if total is not None
        else ""
    )
    suffix = " O resultado foi truncado." if result.truncated else ""
    return (
        f"A consulta retornou {result.row_count} linhas. "
        f"Primeira linha: {preview}.{total_summary}{suffix}"
    )


def _humanize_key(key: str) -> str:
    labels = {
        "DIAG_PRINC": "diagnostico",
        "DESCRICAO": "descricao",
        "total_mortes": "mortes",
        "mortes": "mortes",
        "internacoes": "internacoes",
        "valor_total": "valor total",
    }
    return labels.get(key, key.replace("_", " ").lower())


def _count_column(row: dict[str, Any]) -> str | None:
    for candidate in ("total_mortes", "mortes", "obitos", "internacoes", "total"):
        if candidate in row:
            return candidate
    for key, value in row.items():
        if isinstance(value, int | float) and key.upper() not in {"DIAG_PRINC", "CID"}:
            return key
    return None


def _row_to_user_phrase(row: dict[str, Any]) -> str:
    count_key = _count_column(row)
    count_value = row.get(count_key) if count_key else None
    description = row.get("DESCRICAO") or row.get("descricao") or row.get("NO_MUNICIPIO")
    code = row.get("DIAG_PRINC") or row.get("CID")

    if description and code and count_key:
        count_label = _humanize_key(count_key)
        return f"{description} ({code}): {_format_value(count_value)} {count_label}"
    if description and count_key:
        count_label = _humanize_key(count_key)
        return f"{description}: {_format_value(count_value)} {count_label}"

    return ", ".join(
        f"{_humanize_key(key)}={_format_field_value(key, value)}" for key, value in row.items()
    )


def _should_rank_by_count(question: str) -> bool:
    text = normalize_text(question)
    return any(token in text.split() for token in ("mais", "maior", "maiores", "top", "ranking"))


def _presentation_rows(question: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _should_rank_by_count(question):
        return rows
    sortable = []
    for row in rows:
        count_key = _count_column(row)
        count_value = row.get(count_key) if count_key else None
        if not isinstance(count_value, int | float):
            return rows
        sortable.append((count_value, row))
    return [row for _, row in sorted(sortable, key=lambda item: item[0], reverse=True)]


def _geography_label(value: str) -> str:
    return {
        "residence": "municipio de residencia",
        "hospital": "municipio do hospital/atendimento",
        "mixed": "geografia mista",
        "none": "sem recorte geografico explicito",
    }.get(value, value)


def _year_column(row: dict[str, Any]) -> str | None:
    for candidate in ("ano", "ano_entrada", "ano_saida", "year"):
        if candidate in row:
            return candidate
    for key in row:
        if "ano" in key.lower():
            return key
    return None


def _count_label(count_key: str | None) -> str:
    if not count_key:
        return "registros"
    label = _humanize_key(count_key)
    if label == "total":
        return "registros"
    return label


def _series_phrase(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    year_key = _year_column(rows[0])
    count_key = _count_column(rows[0])
    if not year_key or not count_key:
        return None
    if not all(year_key in row and count_key in row for row in rows):
        return None
    visible_rows = rows[:24]
    pairs = "; ".join(
        f"{_format_field_value(year_key, row[year_key])}: {_format_value(row[count_key])}"
        for row in visible_rows
    )
    suffix = "; ..." if len(rows) > len(visible_rows) else ""
    return f"Por ano: {pairs}{suffix}."


TECHNICAL_ANSWER_PREFIXES = (
    "base temporal",
    "caveat",
    "caveats",
    "observacao",
    "observacoes",
    "detalhe",
    "detalhes",
    "metrica",
    "metricas",
    "filtro",
    "filtros",
    "sql",
    "validacao",
    "contexto anterior",
)


def _strip_developer_details(answer: str) -> str:
    paragraphs = [paragraph.strip() for paragraph in answer.splitlines() if paragraph.strip()]
    kept = []
    for paragraph in paragraphs:
        normalized = normalize_text(paragraph).strip()
        if any(normalized.startswith(prefix) for prefix in TECHNICAL_ANSWER_PREFIXES):
            continue
        if "considerei o contexto anterior" in normalized:
            continue
        paragraph = re.split(
            r"\s+(?:Base temporal|Caveats?|Observações?|Observacoes?|Detalhes?|M[eé]trica|SQL|Validação|Validacao):",
            paragraph,
            maxsplit=1,
            flags=re.I,
        )[0].strip()
        if not paragraph:
            continue
        kept.append(paragraph)
    return "\n\n".join(kept).strip() or answer.strip()


def _build_user_answer(
    *,
    question: str,
    plan: SqlPlan,
    execution: ExecutionResult,
    caveats: list[str],
    related_context: list[dict[str, Any]],
) -> str:
    presentation_rows = _presentation_rows(question, execution.rows)

    if not presentation_rows:
        return "Não encontrei registros para essa pergunta."
    elif len(presentation_rows) == 1:
        row = presentation_rows[0]
        count_key = _count_column(row)
        if count_key and len(row) == 1:
            return f"Foram {_format_value(row[count_key])} {_count_label(count_key)}."
        return f"O resultado foi: {_row_to_user_phrase(row)}."
    else:
        if _should_rank_by_count(question):
            rows = [
                f"{idx}. {_row_to_user_phrase(row)}"
                for idx, row in enumerate(presentation_rows[:10], start=1)
            ]
            suffix = "; ..." if len(presentation_rows) > 10 else ""
            return "Os resultados foram: " + "; ".join(rows) + suffix + "."

        count_key = _count_column(presentation_rows[0])
        total = None
        if count_key and all(
            isinstance(row.get(count_key), int | float) for row in presentation_rows
        ):
            total = sum(row[count_key] for row in presentation_rows)
        if total is not None:
            answer = f"Foram {_format_value(total)} {_count_label(count_key)} no período analisado."
        else:
            rows = [
                f"{idx}. {_row_to_user_phrase(row)}"
                for idx, row in enumerate(presentation_rows[:10], start=1)
            ]
            suffix = "; ..." if len(presentation_rows) > 10 else ""
            answer = "Os resultados foram: " + "; ".join(rows) + suffix + "."

        if series := _series_phrase(presentation_rows):
            answer += f"\n\n{series}"
        return answer


def _build_developer_context(
    *,
    plan: SqlPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
    context: RetrievedContext | None,
    related_context: list[dict[str, Any]],
    caveats: list[str],
    chart_plan: ChartPlan | None = None,
    chart_payload: ChartPayload | None = None,
) -> dict[str, Any]:
    context_payload = {
        "technical_summary": _summarize_result(execution),
        "metric_basis": plan.metric_basis,
        "date_basis": plan.date_basis,
        "geography_basis": plan.geography_basis,
        "join_assumptions": plan.join_assumptions,
        "retrieved_tables": context.tables if context else [],
        "retrieval_mode": context.retrieval_mode if context else "",
        "business_metrics": [metric.model_dump() for metric in context.business_metrics]
        if context
        else [],
        "value_hints": [hint.model_dump() for hint in context.value_hints] if context else [],
        "catalog_candidates": [candidate.model_dump() for candidate in context.catalog_candidates]
        if context
        else [],
        "catalog_tool_calls": [call.model_dump() for call in context.catalog_tool_calls]
        if context
        else [],
        "catalog_decisions": [decision.model_dump() for decision in plan.catalog_decisions],
        "query_examples": [
            {
                "id": example.id,
                "question_pt": example.question_pt,
                "expected_result_type": example.expected_result_type,
            }
            for example in context.query_examples
        ]
        if context
        else [],
        "warnings": validation.warnings,
        "caveats": caveats,
        "related_context": related_context,
    }
    if chart_plan is not None and chart_plan.requested:
        context_payload["chart_plan"] = chart_plan.model_dump()
    if chart_payload is not None:
        context_payload["chart_spec"] = (
            chart_payload.spec.model_dump() if chart_payload.spec is not None else None
        )
        context_payload["chart_warnings"] = [
            warning.model_dump() for warning in chart_payload.warnings
        ]
    return context_payload


def _compact_result_rows(
    rows: list[dict[str, Any]], *, limit: int = NATURAL_ANSWER_ROW_LIMIT
) -> list[dict[str, Any]]:
    return rows[:limit]


def _natural_answer_context(
    *,
    question: str,
    plan: SqlPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
    result_summary: str,
    caveats: list[str],
    related_context: list[dict[str, Any]],
) -> dict[str, str]:
    return {
        "question": question,
        "sql": execution.sql,
        "result_summary": result_summary,
        "result_rows": json.dumps(
            _compact_result_rows(execution.rows),
            ensure_ascii=False,
            default=str,
        ),
        "plan": json.dumps(
            {
                "metric_basis": plan.metric_basis,
                "date_basis": plan.date_basis,
                "geography_basis": plan.geography_basis,
                "grain": plan.grain,
                "join_assumptions": plan.join_assumptions,
                "caveats": plan.caveats,
            },
            ensure_ascii=False,
            default=str,
        ),
        "validation": json.dumps(
            {
                "warnings": validation.warnings,
                "severity": validation.severity,
            },
            ensure_ascii=False,
            default=str,
        ),
        "caveats": json.dumps(caveats, ensure_ascii=False, default=str),
        "related_context": json.dumps(
            [
                {
                    "question": item.get("question"),
                    "answer_status": item.get("answer_status"),
                    "result_summary": item.get("result_summary"),
                    "caveats": item.get("caveats", []),
                }
                for item in related_context[:3]
            ],
            ensure_ascii=False,
            default=str,
        ),
    }


def _contextual_caveats(question: str, context: RetrievedContext | None) -> list[str]:
    if context is None:
        return []

    normalized_question = normalize_text(question)
    municipality_ufs: dict[str, set[str]] = {}
    display_names: dict[str, str] = {}
    for hint in context.value_hints:
        if hint.table != "municipios" or hint.column != "NO_MUNICIPIO":
            continue
        name = str(hint.value)
        normalized_name = normalize_text(name)
        if normalized_name not in normalized_question:
            continue
        display_names.setdefault(normalized_name, name)
        if hint.label:
            municipality_ufs.setdefault(normalized_name, set()).add(str(hint.label))

    caveats = []
    for normalized_name, ufs in municipality_ufs.items():
        if len(ufs) <= 1:
            continue
        caveats.append(
            f"O municipio '{display_names[normalized_name]}' aparece em mais de uma UF "
            f"nos hints ({', '.join(sorted(ufs))}); sem UF explicita, a consulta pode "
            "incluir municipios homonimos."
        )
    return caveats


def _build_llm_user_answer(
    *,
    question: str,
    plan: SqlPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
    result_summary: str,
    caveats: list[str],
    related_context: list[dict[str, Any]],
    config: ChatbotConfig | None,
    allow_llm: bool,
) -> tuple[str, str | None]:
    fallback = _build_user_answer(
        question=question,
        plan=plan,
        execution=execution,
        caveats=caveats,
        related_context=related_context,
    )
    if not allow_llm:
        return fallback, "Natural-language LLM synthesis disabled; used deterministic fallback."
    if config is None:
        return fallback, "Missing ChatbotConfig; used deterministic fallback."
    if config.agent_framework == "pydantic_ai":
        return _build_pydantic_ai_user_answer(
            question=question,
            plan=plan,
            validation=validation,
            execution=execution,
            result_summary=result_summary,
            caveats=caveats,
            related_context=related_context,
            config=config,
            fallback=fallback,
        )
    if config.agent_framework != "llamaindex":
        return fallback, f"Unsupported agent framework {config.agent_framework}; used deterministic fallback."
    return _build_llamaindex_user_answer(
        question=question,
        plan=plan,
        validation=validation,
        execution=execution,
        result_summary=result_summary,
        caveats=caveats,
        related_context=related_context,
        config=config,
        fallback=fallback,
    )


def _build_pydantic_ai_user_answer(
    *,
    question: str,
    plan: SqlPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
    result_summary: str,
    caveats: list[str],
    related_context: list[dict[str, Any]],
    config: ChatbotConfig,
    fallback: str,
) -> tuple[str, str | None]:
    try:
        agent = build_answer_agent(config)
        deps = AnswerDeps(
            config=config,
            question=question,
            plan=plan,
            validation=validation,
            execution=execution,
            caveats=caveats,
            related_context=related_context,
        )
        answer = agent.run_sync(
            NATURAL_ANSWER_PROMPT.format(
                **_natural_answer_context(
                    question=question,
                    plan=plan,
                    validation=validation,
                    execution=execution,
                    result_summary=result_summary,
                    caveats=caveats,
                    related_context=related_context,
                )
            ),
            deps=deps,
        )
        answer_pt = _strip_developer_details(answer.output.answer_pt.strip())
        if answer_pt:
            return answer_pt, None
        return fallback, "Natural-language Pydantic AI synthesis returned an empty answer; used deterministic fallback."
    except Exception as exc:
        return fallback, f"Natural-language Pydantic AI synthesis failed; used deterministic fallback: {exc}"


def _build_llamaindex_user_answer(
    *,
    question: str,
    plan: SqlPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
    result_summary: str,
    caveats: list[str],
    related_context: list[dict[str, Any]],
    config: ChatbotConfig,
    fallback: str,
) -> tuple[str, str | None]:
    try:
        llm = build_openai_llm(config)
        answer = llm.structured_predict(
            NaturalAnswer,
            PromptTemplate(NATURAL_ANSWER_PROMPT),
            **_natural_answer_context(
                question=question,
                plan=plan,
                validation=validation,
                execution=execution,
                result_summary=result_summary,
                caveats=caveats,
                related_context=related_context,
            ),
        )
        answer_pt = _strip_developer_details(answer.answer_pt.strip())
        if answer_pt:
            return answer_pt, None
        return fallback, "Natural-language LLM returned an empty answer; used deterministic fallback."
    except Exception as exc:
        return fallback, f"Natural-language LLM synthesis failed; used deterministic fallback: {exc}"


def _filter_debug_payload(answer: ChatbotAnswer, *, show_debug: bool) -> ChatbotAnswer:
    if show_debug:
        return answer
    return answer.model_copy(
        update={
            "result_summary": "",
            "caveats": [],
            "developer_context": {},
            "evidence": {},
        }
    )


def synthesize_answer(
    *,
    question: str,
    intent: QuestionIntent,
    plan: SqlPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
    context: RetrievedContext | None = None,
    related_context: list[dict[str, Any]] | None = None,
    show_sql: bool = False,
    show_debug: bool = False,
    config: ChatbotConfig | None = None,
    allow_llm: bool = True,
    chart_payload: ChartPayload | None = None,
    chart_plan: ChartPlan | None = None,
) -> ChatbotAnswer:
    caveats = []
    caveats.extend(intent.required_caveats)
    caveats.extend(plan.caveats)
    caveats.extend(_contextual_caveats(question, context))
    caveats = [c for c in dict.fromkeys(caveats) if c]
    related_context = related_context or []

    result_summary = _summarize_result(execution)
    answer_pt, natural_answer_warning = _build_llm_user_answer(
        question=question,
        plan=plan,
        validation=validation,
        execution=execution,
        result_summary=result_summary,
        caveats=caveats,
        related_context=related_context,
        config=config,
        allow_llm=allow_llm,
    )
    answer_source = "deterministic_fallback"
    if allow_llm and config is not None and not natural_answer_warning:
        answer_source = (
            "pydantic_ai_openai"
            if config.agent_framework == "pydantic_ai"
            else "llamaindex_openai"
        )
    developer_context = _build_developer_context(
        plan=plan,
        validation=validation,
        execution=execution,
        context=context,
        related_context=related_context,
        caveats=caveats,
        chart_plan=chart_plan,
        chart_payload=chart_payload,
    )
    developer_context["answer_source"] = answer_source
    if natural_answer_warning:
        developer_context["natural_answer_warning"] = natural_answer_warning

    answer = ChatbotAnswer(
        answer_pt=answer_pt,
        sql=execution.sql if show_sql else "",
        result_summary=result_summary,
        caveats=caveats,
        developer_context=developer_context,
        evidence={
            "result_hash": execution.result_hash,
            "elapsed_seconds": execution.elapsed_seconds,
            "row_count": execution.row_count,
            "truncated": execution.truncated,
            "plan_source": plan.source,
            "answer_source": answer_source,
            "chart_requested": bool(chart_payload and chart_payload.requested),
            "chart_rendered": bool(
                chart_payload
                and chart_payload.spec is not None
                and chart_payload.spec.chartable
                and chart_payload.echarts is not None
            ),
        },
        chart=chart_payload,
        status="answered",
    )
    return _filter_debug_payload(answer, show_debug=show_debug)


def clarification_answer(intent: QuestionIntent, *, show_debug: bool = False) -> ChatbotAnswer:
    detail = " ".join(intent.ambiguities) if intent.ambiguities else intent.reason
    answer = ChatbotAnswer(
        answer_pt=f"Preciso de esclarecimento antes de consultar o banco. {detail}",
        status="clarified",
        caveats=intent.required_caveats,
        developer_context={"intent_reason": intent.reason},
        evidence={"intent_reason": intent.reason},
    )
    return _filter_debug_payload(answer, show_debug=show_debug)


def refused_answer(intent: QuestionIntent, *, show_debug: bool = False) -> ChatbotAnswer:
    answer = ChatbotAnswer(
        answer_pt=f"Nao vou executar SQL para essa pergunta. {intent.reason}",
        status="refused",
        caveats=intent.required_caveats,
        developer_context={"intent_reason": intent.reason},
        evidence={"intent_reason": intent.reason},
    )
    return _filter_debug_payload(answer, show_debug=show_debug)


def failed_answer(message: str, *, show_debug: bool = False) -> ChatbotAnswer:
    answer = ChatbotAnswer(
        answer_pt=f"Nao foi possivel responder com seguranca. {message}",
        status="failed",
        developer_context={"error": message},
        evidence={"error": message},
    )
    return _filter_debug_payload(answer, show_debug=show_debug)
