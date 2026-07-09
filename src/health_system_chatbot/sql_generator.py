from __future__ import annotations

from .agent_deps import ChatDeps
from .agents import build_sql_plan_agent
from .catalogs.models import CatalogCandidate, CatalogDecision
from .catalogs.retriever import CatalogRetriever
from .config import ChatbotConfig
from .models import RetrievedContext, SqlPlan, Stage1Context
from .prompts import SQL_GENERATION_PROMPT
from .schema_linking import DIMENSION_LINKS, description_required_for_link
from .text import normalize_text


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


def _shape_guidance(question: str) -> str:
    text = normalize_text(question)
    tokens = set(text.split())
    lines: list[str] = []
    if tokens & {"mais", "maiores", "ranking", "top"}:
        lines.append(
            "- Pergunta de ranking: retorne dimensao + metrica, ordene pela metrica DESC "
            "e use LIMIT 20 se o usuario nao pedir outro limite. Acrescente desempate "
            "deterministico por dimensao legivel quando houver empate na metrica."
        )
    if any(term in text for term in ("percentual", "porcentagem", "participacao", "taxa", "media")):
        lines.append(
            "- Quando ordenar percentual, taxa ou media, inclua desempate deterministico "
            "por dimensoes retornadas, sem mudar o shape da resposta; por exemplo: "
            "ORDER BY ano, percentual_no_ano DESC, capitulo_cid ASC."
        )
    if any(term in text for term in ("distribuicao", "distribuem", "por carater", "por sexo", "por marca", "por uf")):
        lines.append(
            "- Pergunta de distribuicao: retorne a dimensao legivel e a metrica principal; "
            "nao adicione percentual, codigo auxiliar ou coluna extra sem pedido explicito."
        )
    if "rs" in tokens or "uf" in tokens or "estado" in tokens:
        lines.append(
            "- Colunas usadas apenas como filtro constante, como SG_UF = 'RS', nao devem "
            "aparecer na saida salvo se o usuario pedir explicitamente UF/estado como coluna."
        )
    if any(term in text for term in ("compare", "comparar", "comparacao")) and any(
        term in text for term in ("por ano", "ao longo dos anos", "evolucao anual")
    ):
        lines.append(
            "- Comparacao temporal entre grupos nomeados: use uma linha por ano e uma coluna "
            "de metrica para cada grupo comparado, salvo se o usuario pedir formato longo."
        )
    if any(term in text for term in ("auditoria", "sem correspondencia", "nao mapeado", "orfa")):
        lines.append(
            "- Pergunta de auditoria de dimensao: preserve o shape com "
            "COUNT(*) FILTER (WHERE dimensao.chave IS NULL) AS sem_correspondencia "
            "e COUNT(*) AS internacoes."
        )
    if tokens & {"mix"}:
        lines.append(
            "- Pergunta de mix: use formato longo com dimensao A, dimensao B e metrica; "
            "nao inclua percentual salvo se solicitado."
        )
    if "intervalo" in tokens and any(term in text for term in ("data", "datas", "ano", "anos")):
        lines.append(
            "- Pergunta de intervalo temporal: retorne primeiro MIN(...) como primeira_data/primeiro_ano, "
            "depois MAX(...) como ultima_data/ultimo_ano, e por ultimo COUNT(*) como dias/registros."
        )
    return "\n".join(lines)


def _domain_guidance(question: str, context: RetrievedContext) -> str:
    text = normalize_text(question)
    tokens = set(text.split())
    lines: list[str] = []
    cid_hint_columns = {
        hint.column for hint in context.value_hints if hint.table == "cid"
    }
    if cid_hint_columns:
        lines.append(
            "- Quando Value hints de cid forem recuperados para um termo clinico, use "
            "internacoes.DIAG_PRINC -> cid.CID e filtre pelo CID, DS_GRUPO ou "
            "DS_CAPITULO sugerido. Nao invente codigos CID quando o catalogo retornou "
            "candidatos reais."
        )
        if "DS_GRUPO" in cid_hint_columns:
            lines.append(
                "- Um Value hint cid.DS_GRUPO como 'O80-O84 Parto' representa uma faixa/grupo "
                "com subcodigos. Nao transforme isso em DIAG_PRINC IN ('O80','O81',...). "
                "Prefira JOIN cid c ON internacoes.DIAG_PRINC = c.CID e filtre "
                "c.DS_GRUPO pelo valor sugerido."
            )
    death_terms = {
        "morte",
        "mortes",
        "obito",
        "obitos",
        "morreu",
        "morreram",
        "falecimento",
        "faleceram",
    }
    if tokens & death_terms:
        lines.append(
            "- Quando a pergunta disser morte, mortes, obito, obitos, morreu, morreram "
            "ou faleceram, filtre obito hospitalar com internacoes.MORTE = TRUE. "
            "Nao conte apenas internacoes com diagnostico sem aplicar MORTE = TRUE."
        )
        lines.append(
            "- Para causa analitica da morte, use internacoes.DIAG_PRINC como diagnostico "
            "principal junto com internacoes.MORTE = TRUE; CID_MORTE nao e o default."
        )
    if tokens & {"mulher", "mulheres", "feminino", "feminina"}:
        lines.append(
            "- Para mulheres/feminino, os valores reais da dimensao sexo indicam dois "
            "codigos femininos: internacoes.SEXO IN (2, 3). Use esse filtro ou faca "
            "JOIN sexo e filtre sexo.DESCRICAO = 'Feminino'; nao use apenas SEXO = 2."
        )
    if tokens & {"homem", "homens", "masculino", "masculina"}:
        lines.append(
            "- Para homens/masculino, use internacoes.SEXO = 1 ou JOIN sexo filtrando "
            "sexo.DESCRICAO = 'Masculino'."
        )
    if tokens & {"parto", "partos"}:
        lines.append(
            "- Para pergunta simples como 'quantos partos aconteceram?', use procedimento "
            "principal realizado: internacoes.PROC_REA IN ('0310010039','0310010047',"
            "'0310010055','0411010026','0411010034','0411010042'). Essa e a metrica "
            "canonica de partos no banco atual."
        )
        lines.append(
            "- Nao use DIAG_PRINC LIKE 'O8%' para contar partos: O85-O89 inclui "
            "complicacoes do puerperio. Quando a pergunta pedir internacoes com diagnostico "
            "de parto, use JOIN cid e filtre cid.DS_GRUPO = 'O80-O84 Parto' para incluir "
            "subcodigos como O800/O821; nao use apenas DIAG_PRINC IN ('O80','O81','O82','O83','O84')."
        )
    if tokens & {"cesariano", "cesarianos", "cesariana", "cesarianas"}:
        if "internacoes por" in text or "internacoes de" in text or "diagnostico" in text:
            lines.append(
                "- Quando a pergunta disser internacoes por/de parto cesariano, trate como "
                "diagnostico principal e use CID O82: internacoes.DIAG_PRINC LIKE 'O82%' "
                "ou JOIN cid com candidato de catalogo equivalente. Use procedimento "
                "apenas se a pergunta falar em procedimento realizado ou partos que aconteceram."
            )
        else:
            lines.append(
                "- Para partos cesarianos que aconteceram ou procedimento realizado, use "
                "procedimento principal: internacoes.PROC_REA IN "
                "('0411010026','0411010034','0411010042')."
            )
    if "cid c" in text or "cid-c" in text:
        lines.append(
            "- Quando a pergunta disser CID C, use prefixo de codigo: "
            "internacoes.DIAG_PRINC LIKE 'C%' ou cid.CID LIKE 'C%'."
        )
        if "por ano" in text:
            lines.append(
                "- Para serie temporal de eventos com CID C, filtre o universo no WHERE "
                "(WHERE MORTE AND DIAG_PRINC LIKE 'C%') antes do GROUP BY; nao use "
                "COUNT(*) FILTER que mantenha anos com zero eventos."
            )
    if "cancer" in text or "neoplasia" in text:
        lines.append(
            "- Para cancer/neoplasia maligna operacional, prefira codigos CID com prefixo C. "
            "Nao use cid.DS_CAPITULO = 'Neoplasias'; os valores reais incluem textos como "
            "'II. Neoplasias [tumores]'."
        )
        lines.append(
            "- Quando cancer/neoplasia for apenas filtro de uma contagem, taxa ou serie temporal, "
            "nao e obrigatorio retornar a descricao CID; use internacoes.DIAG_PRINC LIKE 'C%' "
            "ou cid.CID LIKE 'C%' e junte cid apenas se a pergunta pedir descricao/diagnostico "
            "como coluna de saida."
        )
        if tokens & death_terms:
            lines.append(
                "- Exemplo de mortes por cancer por cidade e ano: SELECT year(i.DT_INTER) AS ano, "
                "COUNT(*) AS mortes FROM internacoes i JOIN municipios m ON "
                "i.MUNIC_RES = m.CO_MUNICIPIO_6D WHERE i.MORTE = TRUE AND "
                "i.DIAG_PRINC LIKE 'C%' AND m.NO_MUNICIPIO = '<cidade>' GROUP BY 1 ORDER BY 1."
            )
    if any(term in text for term in ("cidade", "municipio", "santa maria")):
        lines.append(
            "- Para filtrar cidade/municipio por nome, use municipios.NO_MUNICIPIO e, quando a "
            "UF estiver clara, municipios.SG_UF. Se houver cidades homonimas e a UF nao estiver "
            "clara, inclua SG_UF na saida ou registre caveat de ambiguidade."
        )
    if "descricao cid" in text or "com descricao cid" in text:
        lines.append(
            "- Quando pedir diagnosticos/CID com descricao, retorne o codigo CID e a descricao: "
            "cid.CID, cid.DESCRICAO, COUNT(*) AS internacoes."
        )
    if "contraceptivo 1" in text:
        lines.append(
            "- 'contraceptivo 1' se refere a coluna internacoes.CONTRACEP1; "
            "nao interprete como filtro CONTRACEP1 = 1 salvo se o usuario disser codigo/valor igual a 1."
        )
        lines.append(
            "- Para distribuicao por tipo de contraceptivo 1, faca JOIN contraceptivos "
            "e retorne somente contraceptivos.DESCRICAO e COUNT(*) AS internacoes; "
            "nao crie bucket extra de sem correspondencia salvo em pergunta de auditoria."
        )
    if "contraceptivo 2" in text:
        lines.append(
            "- 'contraceptivo 2' se refere a coluna internacoes.CONTRACEP2; "
            "nao interprete como filtro CONTRACEP2 = 2 salvo se o usuario disser codigo/valor igual a 2."
        )
    if "procedimento principal" in text or "procedimentos principais" in text:
        lines.append(
            "- Procedimento principal da internacao usa internacoes.PROC_REA -> procedimentos.PROC_REA. "
            "Use tabela de ocorrencias de procedimento somente se ela estiver disponivel no catalogo runtime."
        )
        lines.append(
            "- Para procedimentos principais no catalogo, retorne procedimentos.PROC_REA, "
            "procedimentos.NOME_PROC e COUNT(*) AS internacoes; nao omita o codigo PROC_REA."
        )
    if "internacao_procedimento" in context.tables:
        lines.append(
            "- Atencao: internacao_procedimento pode ser artefato legado. Se o banco atual nao expuser essa "
            "tabela, nao a use; para procedimento principal use internacoes.PROC_REA."
        )
    if "_staging_internacoes" in text or "staging" in text:
        lines.append(
            "- Perguntas sobre staging devem usar _staging_internacoes quando essa tabela estiver disponivel; "
            "nao substitua por internacoes."
        )
        if "carater" in text:
            lines.append(
                "- Para distribuicao da staging por carater, retorne somente car_int.DESCRICAO AS carater "
                "e COUNT(*) AS registros_staging; nao inclua CAR_INT se o usuario nao pedir codigo."
            )
    if "denominador socioeconomico" in text or "populacao socioeconomica" in text:
        lines.append(
            "- Para populacao socioeconomica por UF e ano, retorne SG_UF, ano e SUM(QT_POPULACAO) AS populacao; "
            "nao adicione COUNT(*) AS registros nem internacoes se a pergunta nao pedir."
        )
    if "mix de complexidade por carater" in text:
        lines.append(
            "- Para mix de complexidade por carater, retorne nesta ordem: complexidade, carater, "
            "COUNT(*) AS internacoes; ordene por internacoes DESC."
        )
    return "\n".join(lines)


def _applicable_generation_guidance(context: RetrievedContext, question: str) -> str:
    sections = []
    dimension_guidance = _dimension_guidance(context, question)
    if dimension_guidance:
        sections.append("Schema linking preferencial:\n" + dimension_guidance)
    shape_guidance = _shape_guidance(question)
    if shape_guidance:
        sections.append("Shape esperado da SQL:\n" + shape_guidance)
    domain_guidance = _domain_guidance(question, context)
    if domain_guidance:
        sections.append("Regras de dominio/ambiguidade:\n" + domain_guidance)
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
    normalized_question = normalize_text(question)
    example_lines = []
    for example in context.query_examples[:4]:
        label = (
            "EXEMPLO_EXATO"
            if normalized_question
            and normalize_text(example.question_pt) == normalized_question
            else "EXEMPLO_RELACIONADO"
        )
        example_lines.append(
            f"- {label} {example.id}: {example.question_pt}\n"
            f"  SQL: {example.sql[:1200]}"
        )
    examples = "\n".join(example_lines)
    generation_guidance = _applicable_generation_guidance(context, question)
    return (
        f"Retrieval mode: {context.retrieval_mode}\n\n"
        f"Tabelas:\n{tables}\n\n"
        f"Colunas recuperadas:\n{columns}\n\n"
        f"Metricas de negocio:\n{metrics}\n\n"
        f"Value hints:\n{value_hints}\n\n"
        f"Catalog candidates:\n{catalog_candidates}\n\n"
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
        )
        plan.source = "pydantic_ai_openai"
        return _finalize_plan(question, plan, context=context)

    if config.agent_framework != "llamaindex":
        raise RuntimeError(f"Unsupported agent framework: {config.agent_framework}")

    return _generate_sql_plan_with_llamaindex(
        question,
        context,
        config,
        generation_hint=generation_hint,
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
) -> SqlPlan:
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
    )
    prompt = SQL_GENERATION_PROMPT.format(
        question=question,
        context=_context_to_prompt(context, question),
    )
    if generation_hint:
        prompt += f"\n\nInstrucao adicional para esta candidata:\n{generation_hint}\n"
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
) -> SqlPlan:
    from llama_index.core import PromptTemplate

    from .llm import build_openai_llm

    llm = build_openai_llm(config)
    prompt = PromptTemplate(SQL_GENERATION_PROMPT)
    prompt_context = _context_to_prompt(context, question)
    if generation_hint:
        prompt_context += f"\n\nInstrucao adicional para esta candidata:\n{generation_hint}\n"
    plan = llm.structured_predict(
        SqlPlan,
        prompt,
        question=question,
        context=prompt_context,
    )
    plan.source = "llamaindex_openai"
    return _finalize_plan(question, plan, context=context)
