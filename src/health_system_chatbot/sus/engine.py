"""SUS plan, repair and synthesis flow with the host's SQL and UI contracts."""

from __future__ import annotations

import json
import re
from typing import Any

import duckdb
from openai import APIError, OpenAI

from ..answer_synthesizer import _filter_debug_payload, _summarize_result, failed_answer
from ..config import ChatbotConfig
from ..duckdb_executor import execute_validated_sql
from ..models import ChatbotAnswer, ExecutionResult, Stage1Context
from ..sql_validator import validate_sql
from ..visualization.data import build_chart_planning_input
from ..visualization.intent import detect_visualization_intent
from ..visualization.planner import plan_chart
from ..visualization.renderer_contract import build_chart_payload
from ..visualization.schema import ChartPayload, ChartPlan
from .prompts import ANSWER_SYSTEM_PROMPT, SQL_SCHEMA, SQL_SYSTEM_PROMPT
from .schema_context import build_schema_prompt, capability_notes
from .value_linker import link_values

CHART_KINDS = {
    "linha": "line",
    "barra": "bar",
    "barra_horizontal": "bar",
    "pizza": "pie",
    "dispersao": "scatter",
}


def _complete(client, config, system, user, *, schema_name=None):
    options = {}
    if config.llm_reasoning_effort and config.llm_model.startswith(
        ("gpt-5", "gpt-6", "o1", "o3", "o4")
    ):
        options["reasoning_effort"] = config.llm_reasoning_effort
    if schema_name:
        options["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": SQL_SCHEMA},
        }
    response = client.chat.completions.create(
        model=config.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **options,
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise ValueError("O modelo retornou uma resposta vazia.")
    return text


def _chart(question, plan, result: ExecutionResult) -> ChartPayload | None:
    intent = detect_visualization_intent(question)
    if not intent.requested:
        return None
    kind = intent.chart_hint
    if kind == "auto":
        kind = CHART_KINDS.get(plan.get("kind"), "auto")
    chart_plan = ChartPlan(
        requested=True,
        chart_type=kind,
        x_dimension=plan.get("x"),
        y_column=plan.get("y"),
        series_dimension=plan.get("series"),
    )
    chart_input = build_chart_planning_input(
        user_query=question,
        sql_query=result.sql,
        rows=result.rows,
        columns=result.columns,
        row_count=result.row_count,
        chart_hint=kind,
        chart_plan=chart_plan,
        truncated=result.truncated,
    )
    spec = plan_chart(chart_input)
    if plan.get("title") and spec.chartable:
        spec.title = plan["title"]
    return build_chart_payload(requested=True, spec=spec)


def _answer_input(question, result, assumptions):
    columns = result.columns
    lines = [" | ".join(columns)]
    for row in result.rows[:50]:
        lines.append(
            " | ".join("NULL" if row[c] is None else str(row[c]) for c in columns)
        )
    if len(result.rows) > 50 or result.truncated:
        lines.append("(Prévia limitada; há linhas omitidas.)")
    return (
        f"Pergunta do usuário: {question}\n\nQuery executada:\n{result.sql}\n\n"
        f"Resultado ({result.row_count} linhas na amostra):\n"
        + "\n".join(lines)
        + "\n\nSuposições feitas ao montar a query:\n"
        + "\n".join(assumptions)
    )


def _ask(client, question, config, context, *, show_sql, show_debug, steps):
    system = SQL_SYSTEM_PROMPT.format(
        schema=build_schema_prompt(), capabilities=capability_notes()
    )
    with duckdb.connect(str(config.db_path), read_only=True) as con:
        try:
            hints = link_values(con, question)
        except duckdb.Error:
            # Catalog suggestions are optional; the validated query remains authoritative.
            hints = ""
    prompt = f"Pergunta: {question}"
    if hints:
        prompt += f"\n\n{hints}"
    retries = max(0, config.sql_correction_attempts)
    for attempt in range(retries + 1):
        text = _complete(
            client,
            config,
            system,
            prompt,
            schema_name="correcao_sql" if attempt else "geracao_sql",
        )
        # Port of the original agent's handling of escaped accented characters.
        plan = json.loads(re.sub(r"\\u0000([0-9a-fA-F]{2})", r"\\u00\1", text))
        steps.append({"name": "sql_plan", "payload": plan})
        if not plan["answerable"]:
            return ChatbotAnswer(
                status="refused",
                answer_pt=plan["refusal"] or "A base não contém os dados necessários.",
                developer_context={"engine": "sus", "assumptions": plan["assumptions"]}
                if show_debug
                else {},
            )
        validation = validate_sql(plan["sql"], context)
        steps.append({"name": "validation", "payload": validation.model_dump()})
        try:
            if not validation.is_valid:
                raise ValueError(" ".join(validation.errors))
            result = execute_validated_sql(
                validation,
                db_path=config.db_path,
                max_rows=config.max_rows,
                timeout_seconds=config.sql_timeout_seconds,
            )
        except (ValueError, duckdb.Error, TimeoutError) as exc:
            if attempt >= retries:
                raise
            prompt = (
                f"Pergunta: {question}\n\nEsta query falhou:\n{plan['sql']}\n\n"
                f"Erro: {exc}\nCorrija a query, conferindo o schema e as regras críticas.\n{hints}"
            )
            continue
        break
    steps.append({"name": "execution", "payload": result.model_dump()})
    chart = _chart(question, plan["chart"], result)
    assumptions = plan["assumptions"]
    summary = _summarize_result(result)
    answer_source = "text-to-sql-sus"
    try:
        answer = _complete(
            client,
            config,
            ANSWER_SYSTEM_PROMPT,
            _answer_input(question, result, assumptions),
        )
    except (APIError, ValueError) as exc:
        answer = summary
        answer_source = "execution_summary"
        steps.append(
            {
                "name": "synthesis_fallback",
                "payload": {"error_type": type(exc).__name__},
            }
        )
    return _filter_debug_payload(
        ChatbotAnswer(
            status="answered",
            answer_pt=answer,
            sql=result.sql if show_sql else "",
            result_summary=summary,
            chart=chart,
            caveats=assumptions,
            evidence={
                "plan_source": "text-to-sql-sus",
                "answer_source": answer_source,
                "row_count": result.row_count,
                "elapsed_seconds": result.elapsed_seconds,
                "result_hash": result.result_hash,
                "truncated": result.truncated,
            },
            developer_context={
                "engine": "sus",
                "model": config.llm_model,
                "attempts": attempt + 1,
                "assumptions": assumptions,
                "chart_plan": plan["chart"],
                "columns": result.columns,
                "rows": result.rows,
            },
        ),
        show_debug=show_debug,
    )


def ask(
    question: str,
    config: ChatbotConfig,
    context: Stage1Context,
    *,
    show_sql: bool,
    show_debug: bool,
    steps: list[dict[str, Any]],
) -> ChatbotAnswer:
    try:
        if config.llm_provider != "openai" or not config.has_openai_key:
            raise ValueError("O motor SUS requer o provedor OpenAI e OPENAI_API_KEY.")
        with OpenAI(
            api_key=config.openai_api_key,
            timeout=config.query_timeout_seconds,
            max_retries=1,
        ) as client:
            return _ask(
                client,
                question,
                config,
                context,
                show_sql=show_sql,
                show_debug=show_debug,
                steps=steps,
            )
    except APIError as exc:
        # Provider error bodies can echo request credentials.
        message = f"Falha no provedor do modelo ({type(exc).__name__})."
    except (ValueError, OSError, duckdb.Error, TimeoutError) as exc:
        message = str(exc)
    steps.append({"name": "failure", "payload": {"errors": [message]}})
    return failed_answer(message, show_debug=show_debug)
