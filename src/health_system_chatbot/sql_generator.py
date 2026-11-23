from __future__ import annotations

import inspect

from .agent_deps import ChatDeps
from .agents import build_sql_plan_agent
from .catalogs.models import CatalogCandidate, CatalogDecision
from .catalogs.retriever import CatalogRetriever
from .config import ChatbotConfig
from .errors import RequiredSourceUnavailable
from .models import RetrievedContext, SqlPlan, Stage1Context
from .prompts import SQL_GENERATION_PROMPT
from .schema_linking import DIMENSION_LINKS, description_required_for_link
from .text import normalize_text
from .visualization.schema import ChartPlan


def _infer_grain(question: str, sql: str) -> str:
    text = normalize_text(f"{question} {sql}")
    if "internacao_procedimento" in text or "procedimento" in text:
        return "procedure_occurrence"
    if "hospital" in text or "cnes" in text:
        return "hospital"
    if "municipio" in text and "ano" in text:
        return "municipality_year"
    if "internacao" in text or "internacoes" in text or "aih" in text:
        return "hospitalization"
    return "other"


def _infer_geography(question: str, sql: str) -> str:
    text = normalize_text(f"{question} {sql}")
    tokens = set(text.split())
    has_residence = "munic_res" in text or "residencia" in text
    has_hospital = "munic_mov" in text or "estabelecimento" in tokens or "hospital" in tokens
    if has_residence and has_hospital:
        return "mixed"
    if has_residence:
        return "residence"
    if has_hospital:
        return "hospital"
    return "none"


def _infer_metric_basis(sql: str) -> list[str]:
    upper = sql.upper()
    metrics = []
    for name in ("VAL_TOT", "VAL_SH", "VAL_SP", "VAL_UTI", "DIAS_PERM", "MORTE"):
        if name in upper:
            metrics.append(name)
    if "COUNT(" in upper:
        metrics.append("COUNT")
    return metrics


def _infer_date_basis(sql: str) -> str:
    upper = sql.upper()
    if "DT_INTER" in upper:
        return "DT_INTER"
    if "DT_SAIDA" in upper:
        return "DT_SAIDA"
    if "NU_ANO" in upper:
        return "NU_ANO"
    return "unknown"


def _question_has_any(question: str, terms: tuple[str, ...]) -> bool:
    text = normalize_text(question)
    return any(term in text for term in terms)


def _dimension_guidance(context: RetrievedContext, question: str) -> str:
    retrieved = set(context.tables)
    lines: list[str] = []
    for link in DIMENSION_LINKS:
        if link.fact_table not in retrieved and link.dimension_table not in retrieved:
            continue
        if link.dimension_table not in retrieved and not _question_has_any(question, link.triggers):
            continue
        code_rule = (
            "A pergunta pede codigo; mantenha codigo cru e inclua descricao apenas se solicitada."
            if not description_required_for_link(question, link)
            else f"Para esta pergunta, prefira {link.description_column}."
        )
        lines.append(
            "- "
            f"{link.fact_column} -> {link.dimension_key}; para leitura de negocio por "
            f"{link.business_name}, retorne {link.description_column}. {code_rule}"
        )
    return "\n".join(lines)


def _contract_guidance(context: RetrievedContext) -> str:
    contract = context.question_contract
    if contract is None:
        return ""
    lines: list[str] = []
    lines.append(
        "- Gere somente requisitos presentes no QuestionContract ou em regra "
        "semantica ativa com proveniencia."
    )
    if contract.ranking.n is not None:
        lines.append(f"- A pergunta exige top {contract.ranking.n}.")
    else:
        lines.append("- A pergunta nao declara top-N; nao invente LIMIT.")
    if contract.ranking.partition_by:
        lines.append(
            "- O ranking deve ser particionado explicitamente por: "
            + ", ".join(contract.ranking.partition_by)
            + "."
        )
    else:
        lines.append("- Nao particione ranking por uma dimensao apenas porque ela filtra o universo.")
    if contract.ranking.minimum_support is not None:
        lines.append(
            f"- A pergunta exige suporte minimo {contract.ranking.minimum_support}."
        )
    else:
        lines.append("- Nao invente HAVING/suporte minimo.")
    if contract.time.basis == "unresolved":
        lines.append(
            "- A base temporal esta unresolved; nao trate DT_INTER ou DT_SAIDA "
            "como requisito silencioso. Registre a suposicao ou solicite esclarecimento."
        )
    elif contract.time.basis != "none":
        lines.append(f"- Base temporal exigida: {contract.time.basis}.")
    if contract.required_sources:
        lines.append(
            "- Fontes obrigatorias: " + ", ".join(contract.required_sources)
            + ". Se estiverem ausentes/sem cobertura, pare com required_source_unavailable."
        )
    if contract.output.required_concepts:
        lines.append(
            "- Conceitos obrigatorios de saida: "
            + ", ".join(contract.output.required_concepts)
            + "."
        )
    for ambiguity in contract.ambiguities:
        lines.append(
            f"- Ambiguidade nao resolvida ({ambiguity}); nao a resolva copiando um exemplo."
        )
    for rule in context.semantic_rule_context:
        lines.append(f"- Regra ativa: {rule}")
    return "\n".join(lines)


def _applicable_generation_guidance(context: RetrievedContext, question: str) -> str:
    sections = []
    dimension_guidance = _dimension_guidance(context, question)
    if dimension_guidance:
        sections.append("Schema linking preferencial:\n" + dimension_guidance)
    contract_guidance = _contract_guidance(context)
    if contract_guidance:
        sections.append("Contrato e regras aplicaveis:\n" + contract_guidance)
    return "\n\n".join(sections)


def _context_to_prompt(context: RetrievedContext, question: str = "") -> str:
    policies = "\n".join(
        f"- {p.left} -> {p.right}: {p.confidence}, {p.accepted_usage_policy}, unmatched={p.unmatched_rows}"
        for p in context.join_policies[:12]
    )
    caveats = "\n".join(f"- {c}" for c in context.data_quality_caveats[:8])
    tables = "\n\n".join(context.table_context[:8])
    columns = "\n".join(f"- {column}" for column in context.columns[:160])
    metrics = "\n".join(
        "- "
        + metric.name
        + f": {metric.description}; formula={metric.formula}; columns={', '.join(metric.columns)}; caveats={'; '.join(metric.caveats)}"
        for metric in context.business_metrics[:8]
    )
    value_hints = "\n".join(
        f"- {hint.table}.{hint.column}={hint.value} ({hint.label}) [{hint.match_reason}]"
        for hint in context.value_hints[:12]
    )
    catalog_candidates = "\n".join(
        "- "
        f"{candidate.catalog}.{candidate.source_column}: {candidate.label}; "
        f"level={candidate.level}; filter={candidate.filter.where_sql_template}; "
        f"value={candidate.filter.value}; confidence={candidate.confidence}; "
        f"evidence={'; '.join(candidate.evidence[:2])}"
        for candidate in context.catalog_candidates[:12]
    )
    example_lines = []
    for example in context.query_examples[:4]:
        decision = next(
            (
                item
                for item in context.example_retrieval_decisions
                if item.example_id == example.id
            ),
            None,
        )
        reason = "; ".join(decision.reasons) if decision else "legacy retrieval"
        example_lines.append(
            f"- EXEMPLO_CONDICIONAL {example.id} [{reason}]: {example.question_pt}\n"
            f"  SQL: {example.sql[:1200]}"
        )
    examples = "\n".join(example_lines)
    contract = (
        context.question_contract.model_dump_json(indent=2)
        if context.question_contract is not None
        else "{}"
    )
    semantic_rules = "\n".join(
        f"- {item}" for item in context.semantic_rule_context
    )
    generation_guidance = _applicable_generation_guidance(context, question)
    return (
        f"Retrieval mode: {context.retrieval_mode}\n\n"
        f"Tabelas:\n{tables}\n\n"
        f"Colunas recuperadas:\n{columns}\n\n"
        f"Metricas de negocio:\n{metrics}\n\n"
        f"Value hints:\n{value_hints}\n\n"
        f"Catalog candidates:\n{catalog_candidates}\n\n"
        f"QuestionContract (fonte primaria do shape e da semantica):\n{contract}\n\n"
        f"Regras semanticas ativas com proveniencia:\n{semantic_rules}\n\n"
        f"Exemplos few-shot relacionados:\n{examples}\n\n"
        "Orientacoes aplicaveis para geracao SQL "
        "(prevalecem sobre exemplos legados quando houver conflito):\n"
        f"{generation_guidance}\n\n"
        f"Join policies:\n{policies}\n\n"
        f"Caveats:\n{caveats}"
    )


def generate_sql_plan(
    question: str,
    context: RetrievedContext,
    stage1_context: Stage1Context,
    config: ChatbotConfig,
    *,
    allow_llm: bool = True,
    generation_hint: str = "",
    chart_plan: ChartPlan | None = None,
) -> SqlPlan:
    if not allow_llm:
        raise RuntimeError(
            "LLM generation is disabled. Runtime SQL generation no longer uses ground truth shortcuts."
        )

    if config.agent_framework == "pydantic_ai":
        plan = _generate_sql_plan_with_pydantic_ai(
            question,
            context,
            stage1_context,
            config,
            generation_hint=generation_hint,
            chart_plan=chart_plan,
        )
        plan.source = f"pydantic_ai_{config.llm_provider}"
        return _finalize_plan(question, plan, context=context)

    if config.agent_framework != "llamaindex":
        raise RuntimeError(f"Unsupported agent framework: {config.agent_framework}")

    return _generate_sql_plan_with_llamaindex(
        question,
        context,
        config,
        generation_hint=generation_hint,
        chart_plan=chart_plan,
    )


def _finalize_plan(
    question: str,
    plan: SqlPlan,
    context: RetrievedContext | None = None,
) -> SqlPlan:
    if not plan.metric_basis:
        plan.metric_basis = _infer_metric_basis(plan.sql)
    if plan.date_basis in {"", "none"}:
        plan.date_basis = _infer_date_basis(plan.sql)
    if plan.grain in {"", "other"}:
        plan.grain = _infer_grain(question, plan.sql)
    if plan.geography_basis in {"", "none"}:
        plan.geography_basis = _infer_geography(question, plan.sql)
    if context is not None:
        existing_decisions = _filter_catalog_decisions_used_in_sql(
            plan.sql,
            plan.catalog_decisions,
            context.catalog_candidates,
        )
        plan.catalog_decisions = _merge_catalog_decisions(
            existing_decisions,
            _infer_catalog_decisions(plan.sql, context.catalog_candidates),
        )
    return plan


def _filter_catalog_decisions_used_in_sql(
    sql: str,
    decisions: list[CatalogDecision],
    candidates: list[CatalogCandidate],
) -> list[CatalogDecision]:
    if not decisions:
        return []
    upper = sql.upper()
    filtered: list[CatalogDecision] = []
    for decision in decisions:
        matching_candidates = [
            candidate
            for candidate in candidates
            if candidate.catalog == decision.catalog
            and candidate.label == decision.selected_candidate_label
        ]
        if any(_candidate_used_in_sql(candidate, upper) for candidate in matching_candidates):
            filtered.append(decision)
    return filtered


def _merge_catalog_decisions(
    existing: list[CatalogDecision],
    inferred: list[CatalogDecision],
) -> list[CatalogDecision]:
    if existing:
        existing_catalogs = {decision.catalog for decision in existing}
        inferred = [
            decision for decision in inferred if decision.catalog not in existing_catalogs
        ]
    merged: list[CatalogDecision] = []
    seen: set[tuple[str, str, str]] = set()
    for decision in [*existing, *inferred]:
        key = (
            decision.catalog,
            decision.query,
            decision.selected_candidate_label,
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(decision)
    return merged


def _infer_catalog_decisions(
    sql: str,
    candidates: list[CatalogCandidate],
) -> list[CatalogDecision]:
    upper = sql.upper()
    decisions: list[CatalogDecision] = []
    for candidate in candidates:
        if not _candidate_used_in_sql(candidate, upper):
            continue
        decisions.append(
            CatalogDecision(
                catalog=candidate.catalog,
                query=candidate.label,
                selected_candidate_label=candidate.label,
                selected_filter=_candidate_filter_text(candidate),
                confidence=candidate.confidence,
                alternatives=[],
            )
        )
    return decisions[:8]


def _candidate_used_in_sql(candidate: CatalogCandidate, upper_sql: str) -> bool:
    column = candidate.filter.column.upper()
    if column not in upper_sql:
        return False
    value = candidate.filter.value
    if isinstance(value, list):
        return any(str(item).upper() in upper_sql for item in value)
    return str(value).upper() in upper_sql


def _candidate_filter_text(candidate: CatalogCandidate) -> str:
    value = candidate.filter.value
    if isinstance(value, list):
        value_text = "(" + ", ".join(repr(item) for item in value) + ")"
    else:
        value_text = repr(value)
    return f"{candidate.filter.table}.{candidate.filter.column} {candidate.filter.operator} {value_text}"


def _generate_sql_plan_with_pydantic_ai(
    question: str,
    context: RetrievedContext,
    stage1_context: Stage1Context,
    config: ChatbotConfig,
    *,
    generation_hint: str = "",
    chart_plan: ChartPlan | None = None,
) -> SqlPlan:
    if context.question_contract is not None:
        missing_sources = sorted(
            set(context.question_contract.required_sources) - stage1_context.table_names
        )
        if missing_sources:
            raise RequiredSourceUnavailable(
                "required_source_unavailable:" + ",".join(missing_sources)
            )
    agent = build_sql_plan_agent(config)
    catalog_retriever = (
        CatalogRetriever.from_config(config)
        if config.catalog_tools_enabled and config.db_path.exists()
        else None
    )
    deps = ChatDeps(
        config=config,
        stage1_context=stage1_context,
        retrieved_context=context,
        catalog_retriever=catalog_retriever,
        chart_plan=chart_plan,
    )
    prompt = SQL_GENERATION_PROMPT.format(
        question=question,
        context=_context_to_prompt(context, question),
    )
    if generation_hint:
        prompt += f"\n\nInstrucao adicional para esta candidata:\n{generation_hint}\n"
    if chart_plan is not None and chart_plan.requested:
        prompt += "\n\n" + chart_plan.to_prompt_block() + "\n"
    run_parameters = inspect.signature(agent.run_sync).parameters
    if "usage_limits" in run_parameters:
        from pydantic_ai import UsageLimits

        result = agent.run_sync(
            prompt,
            deps=deps,
            usage_limits=UsageLimits(request_limit=config.agent_request_limit),
        )
    else:
        result = agent.run_sync(prompt, deps=deps)
    if catalog_retriever is not None and catalog_retriever.tool_calls:
        context.catalog_tool_calls.extend(catalog_retriever.tool_calls)
        for call in catalog_retriever.tool_calls:
            if call.result is not None:
                context.catalog_candidates.extend(call.result.candidates)
    return result.output


def _generate_sql_plan_with_llamaindex(
    question: str,
    context: RetrievedContext,
    config: ChatbotConfig,
    *,
    generation_hint: str = "",
    chart_plan: ChartPlan | None = None,
) -> SqlPlan:
    missing_sources = (
        sorted(set(context.question_contract.required_sources) - set(context.tables))
        if context.question_contract is not None
        else []
    )
    if missing_sources:
        raise RequiredSourceUnavailable(
            "required_source_unavailable:"
            + ",".join(missing_sources)
        )
    from llama_index.core import PromptTemplate

    from .llm import build_openai_llm

    llm = build_openai_llm(config)
    prompt = PromptTemplate(SQL_GENERATION_PROMPT)
    prompt_context = _context_to_prompt(context, question)
    if generation_hint:
        prompt_context += f"\n\nInstrucao adicional para esta candidata:\n{generation_hint}\n"
    if chart_plan is not None and chart_plan.requested:
        prompt_context += "\n\n" + chart_plan.to_prompt_block() + "\n"
    plan = llm.structured_predict(
        SqlPlan,
        prompt,
        question=question,
        context=prompt_context,
    )
    plan.source = "llamaindex_openai"
    return _finalize_plan(question, plan, context=context)
