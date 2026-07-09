from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import RetrievedContext, Stage1Context


SQL_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
SQL_START_RE = re.compile(r"\b(SELECT|WITH)\b", re.IGNORECASE)


@dataclass(frozen=True)
class OpenAIGeneration:
    sql: str | None
    raw_text: str
    usage: dict[str, Any] | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None
    cache_hit: bool = False


def extract_sql_from_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        raise ValueError("OpenAI response is empty.")

    fence_match = SQL_FENCE_RE.search(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()

    start_match = SQL_START_RE.search(stripped)
    if not start_match:
        raise ValueError("OpenAI response did not contain SELECT or WITH SQL.")
    sql = stripped[start_match.start() :].strip()
    sql = re.sub(r"^SQL\s*:\s*", "", sql, flags=re.IGNORECASE).strip()
    if not sql:
        raise ValueError("OpenAI response did not contain SQL after cleanup.")
    return sql


def _compact_schema(retrieved: RetrievedContext) -> str:
    lines = ["Tabelas recuperadas:"]
    for table in retrieved.tables:
        lines.append(f"- {table}")
    lines.append("")
    lines.append("Colunas recuperadas:")
    for column in retrieved.columns[:180]:
        lines.append(f"- {column}")
    return "\n".join(lines)


def _retrieved_schema(retrieved: RetrievedContext) -> str:
    sections = [_compact_schema(retrieved)]
    if retrieved.table_context:
        sections.append("")
        sections.append("Contexto de tabelas:")
        sections.extend(retrieved.table_context[:12])
    if retrieved.join_policies:
        sections.append("")
        sections.append("Politicas de relacionamento:")
        for policy in retrieved.join_policies[:12]:
            sections.append(
                f"- {policy.left} -> {policy.right}: {policy.accepted_usage_policy or policy.business_meaning}"
            )
    return "\n".join(sections)


def _full_context(retrieved: RetrievedContext) -> str:
    sections = [_retrieved_schema(retrieved)]
    if retrieved.business_metrics:
        sections.append("")
        sections.append("Metricas de negocio:")
        for metric in retrieved.business_metrics:
            sections.append(f"- {metric.name}: {metric.description}; formula: {metric.formula}")
    if retrieved.value_hints:
        sections.append("")
        sections.append("Value hints reais:")
        for hint in retrieved.value_hints[:20]:
            label = f" ({hint.label})" if hint.label else ""
            sections.append(f"- {hint.table}.{hint.column} = {hint.value}{label}")
    if retrieved.catalog_candidates:
        sections.append("")
        sections.append("Candidatos de catalogo:")
        for candidate in retrieved.catalog_candidates[:20]:
            sections.append(
                f"- {candidate.catalog}: {candidate.code} | {candidate.label} | "
                f"{candidate.filter.where_sql_template}"
            )
    if retrieved.query_examples:
        sections.append("")
        sections.append("Exemplos few-shot relacionados:")
        for example in retrieved.query_examples[:4]:
            sections.append(f"Pergunta: {example.question_pt}")
            sections.append("SQL:")
            sections.append(example.sql)
            sections.append("")
    return "\n".join(sections)


def build_baseline_prompt(
    *,
    question: str,
    retrieved: RetrievedContext,
    stage1_context: Stage1Context,
    mode: str,
) -> str:
    _ = stage1_context
    if mode == "minimal_schema":
        context = _compact_schema(retrieved)
    elif mode in {"retrieved_schema", "one_retry"}:
        context = _retrieved_schema(retrieved)
    elif mode == "full_context":
        context = _full_context(retrieved)
    else:
        raise ValueError(f"Unsupported OpenAI baseline mode: {mode}")

    return f"""Voce gera SQL DuckDB read-only para responder perguntas sobre SIH/SUS.
Retorne apenas uma query SQL. Nao use Markdown, explicacoes ou comentarios.

Regras obrigatorias:
- Use somente SELECT ou WITH.
- Use somente tabelas e colunas listadas no contexto.
- Nunca use INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, COPY, INSTALL, LOAD ou acesso a arquivos.
- Nao gere multiplas statements.
- Se a pergunta pedir ranking ou listagem exploratoria, use LIMIT quando fizer sentido.
- Preserve a semantica da pergunta; nao invente tabelas, colunas, codigos ou valores.

Contexto:
{context}

Pergunta:
{question}
"""


def build_retry_prompt(
    *,
    original_prompt: str,
    previous_sql: str,
    error_message: str,
) -> str:
    return f"""{original_prompt}

A SQL anterior falhou na validacao ou execucao.

SQL anterior:
{previous_sql}

Erro:
{error_message}

Retorne apenas uma nova query SQL DuckDB read-only corrigida.
"""


def _cache_key(*, model: str, prompt: str) -> str:
    payload = json.dumps({"model": model, "prompt": prompt}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_cache(cache_dir: Path, key: str) -> OpenAIGeneration | None:
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return OpenAIGeneration(
        sql=payload.get("sql"),
        raw_text=payload.get("raw_text", ""),
        usage=payload.get("usage"),
        estimated_cost_usd=payload.get("estimated_cost_usd"),
        error=payload.get("error"),
        cache_hit=True,
    )


def _write_cache(cache_dir: Path, key: str, generation: OpenAIGeneration) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    path.write_text(
        json.dumps(
            {
                "sql": generation.sql,
                "raw_text": generation.raw_text,
                "usage": generation.usage,
                "estimated_cost_usd": generation.estimated_cost_usd,
                "error": generation.error,
            },
            indent=2,
            ensure_ascii=True,
            default=str,
        ),
        encoding="utf-8",
    )


def _response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)
    chunks: list[str] = []
    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(str(text))
    return "\n".join(chunks)


def _usage_payload(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {"raw": str(usage)}


def generate_sql_with_openai(
    *,
    prompt: str,
    config: ChatbotConfig,
    cache_dir: Path | None = None,
    use_cache: bool = False,
) -> OpenAIGeneration:
    key = _cache_key(model=config.llm_model, prompt=prompt)
    if use_cache and cache_dir is not None:
        cached = _read_cache(cache_dir, key)
        if cached is not None:
            return cached

    if not config.openai_api_key:
        return OpenAIGeneration(
            sql=None,
            raw_text="",
            error="OPENAI_API_KEY is required for direct OpenAI baseline.",
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.openai_api_key)
        response = client.responses.create(
            model=config.llm_model,
            input=[
                {
                    "role": "system",
                    "content": "Voce e um gerador de SQL DuckDB read-only. Retorne apenas SQL.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw_text = _response_text(response)
        generation = OpenAIGeneration(
            sql=extract_sql_from_text(raw_text),
            raw_text=raw_text,
            usage=_usage_payload(response),
        )
    except Exception as exc:
        generation = OpenAIGeneration(sql=None, raw_text="", error=str(exc))

    if use_cache and cache_dir is not None:
        _write_cache(cache_dir, key, generation)
    return generation
