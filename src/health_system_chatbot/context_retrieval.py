from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .catalogs.models import CatalogCandidate
from .catalogs.retriever import CatalogRetriever
from .config import ChatbotConfig
from .models import (
    BusinessMetric,
    ExampleRetrievalDecision,
    GroundTruthItem,
    QuestionContract,
    RetrievedContext,
    Stage1Context,
    ValueHint,
)
from .question_contract import build_question_contract, mentions_cephalic_delivery
from .semantic_rules import applicable_semantic_rules
from .text import normalize_text, tokenize


BUSINESS_METRICS: tuple[BusinessMetric, ...] = (
    BusinessMetric(
        name="total_partos",
        description=(
            "Contagem de partos por procedimento principal realizado na internacao. "
            "Usar esta metrica como padrao para perguntas simples como 'quantos partos aconteceram'."
        ),
        formula=(
            "COUNT(*) FROM internacao i WHERE EXISTS (SELECT 1 FROM internacao_procedimento ip "
            "WHERE ip.N_AIH = i.N_AIH AND ip.PROC_REA IN "
            "('0310010039','0310010047','0310010055','0411010026','0411010034','0411010042'))"
        ),
        tables=["internacao", "internacao_procedimento", "procedimentos"],
        columns=[
            "internacao_procedimento.N_AIH",
            "internacao_procedimento.PROC_REA",
            "procedimentos.NOME_PROC",
        ],
        caveats=[
            "A unidade de analise e internacao/AIH com procedimento realizado de parto.",
            "Nao use COUNT(*) em internacao_procedimento: AIHs repetem linhas.",
            "Nao usar DIAG_PRINC LIKE 'O8%' como padrao: O85-O89 inclui complicacoes do puerperio.",
        ],
        trigger_terms=["parto", "partos"],
    ),
    BusinessMetric(
        name="partos_cesarianos",
        description="Contagem de partos cesarianos por procedimento principal realizado.",
        formula=(
            "COUNT(*) FROM internacao i WHERE EXISTS (SELECT 1 FROM internacao_procedimento ip "
            "WHERE ip.N_AIH = i.N_AIH AND ip.PROC_REA IN ('0411010026','0411010034','0411010042'))"
        ),
        tables=["internacao", "internacao_procedimento", "procedimentos"],
        columns=[
            "internacao_procedimento.N_AIH",
            "internacao_procedimento.PROC_REA",
            "procedimentos.NOME_PROC",
        ],
        caveats=["A unidade de analise e internacao/AIH com procedimento realizado cesariano."],
        trigger_terms=["cesariano", "cesarianos", "cesariana", "cesarianas"],
    ),
    BusinessMetric(
        name="total_mortes_hospitalares",
        description="Contagem de internacoes/AIH que resultaram em obito hospitalar.",
        formula="COUNT(*) FROM internacao WHERE internacao.MORTE = TRUE",
        tables=["internacao"],
        columns=["internacao.MORTE"],
        caveats=["A unidade de analise e internacao/AIH, nao paciente unico."],
        trigger_terms=[
            "morte",
            "mortes",
            "obito",
            "obitos",
            "morreu",
            "morreram",
            "falecimento",
            "faleceram",
        ],
    ),
    BusinessMetric(
        name="total_internacoes",
        description="Contagem de internacoes hospitalares/AIH na tabela principal.",
        formula="COUNT(*) FROM internacao",
        tables=["internacao"],
        columns=[],
        caveats=["A unidade de analise e internacao/AIH, nao paciente unico."],
        trigger_terms=["internacao", "internacoes", "aih", "total", "quantas"],
    ),
    BusinessMetric(
        name="taxa_mortalidade_hospitalar",
        description="Taxa bruta de mortalidade hospitalar.",
        formula="100.0 * COUNT(*) FILTER (WHERE internacao.MORTE) / COUNT(*)",
        tables=["internacao"],
        columns=["internacao.MORTE"],
        caveats=["Declarar denominador, periodo e filtros usados."],
        trigger_terms=["mortalidade", "morte", "mortes", "obito", "obitos", "taxa"],
    ),
    BusinessMetric(
        name="valor_total_aprovado",
        description="Valor total aprovado registrado em VAL_TOT.",
        formula="SUM(internacao.VAL_TOT)",
        tables=["internacao"],
        columns=["internacao.VAL_TOT"],
        caveats=["Declarar que a base financeira e VAL_TOT."],
        trigger_terms=["valor", "custo", "financeiro", "aprovado", "val_tot"],
    ),
    BusinessMetric(
        name="permanencia_media",
        description="Media de dias de permanencia hospitalar.",
        formula="AVG(internacao.DIAS_PERM)",
        tables=["internacao"],
        columns=["internacao.DIAS_PERM"],
        caveats=["Verificar qualidade e completude de DIAS_PERM."],
        trigger_terms=["permanencia", "dias", "media"],
    ),
    BusinessMetric(
        name="procedimentos_ocorrencias",
        description=(
            "Contagem em internacao_procedimento muda o grao para ocorrencia de procedimento; "
            "para internacoes com o procedimento use COUNT(DISTINCT N_AIH)."
        ),
        formula="COUNT(DISTINCT internacao_procedimento.N_AIH) FROM internacao_procedimento",
        tables=["internacao_procedimento", "procedimentos"],
        columns=["internacao_procedimento.N_AIH", "internacao_procedimento.PROC_REA"],
        caveats=[
            "Nao interpretar COUNT(*) em internacao_procedimento como numero de internacoes: "
            "AIHs de longa permanencia repetem linhas.",
        ],
        trigger_terms=["procedimento", "procedimentos", "proc_rea", "ocorrencia"],
    ),
    BusinessMetric(
        name="geografia_residencia",
        description="Geografia do usuario/paciente via municipio de residencia.",
        formula="internacao.MUNIC_RES -> municipios.CO_MUNICIPIO_6D",
        tables=["internacao", "municipios"],
        columns=["internacao.MUNIC_RES", "municipios.NO_MUNICIPIO", "municipios.SG_UF"],
        caveats=["Declarar universo mapeado ou usar LEFT JOIN com bucket sem correspondencia."],
        trigger_terms=["residencia", "residentes", "moradores", "municipio", "uf"],
    ),
    BusinessMetric(
        name="geografia_hospital",
        description="Geografia do estabelecimento de atendimento via CNES do hospital.",
        formula=(
            "internacao.CNES -> hospital.CNES; hospital.MUNIC_MOV -> municipios.CO_MUNICIPIO_6D"
        ),
        tables=["internacao", "hospital", "municipios"],
        columns=["internacao.CNES", "hospital.NO_HOSPITAL", "hospital.MUNIC_MOV"],
        caveats=[
            "Municipio do hospital difere do municipio de residencia; declare qual foi usado.",
            "23 hospitais tem MUNIC_MOV sem correspondencia em municipios; use LEFT JOIN.",
        ],
        trigger_terms=["hospital", "hospitais", "estabelecimento", "atendimento", "cnes"],
    ),
)


PLACE_QUERY_RE = re.compile(
    r"\b(?:em|de|do|da|no|na)\s+([A-Za-z][A-Za-z -]{2,40})"
)


def retrieve_metric_context(question: str) -> list[BusinessMetric]:
    question_tokens = tokenize(question)
    normalized = normalize_text(question)
    asks_diagnosis_scope = (
        mentions_cephalic_delivery(normalized)
        or "diagnostico" in normalized
        or "cid" in normalized
        or "internacoes por" in normalized
        or "internacoes de" in normalized
    )
    selected = []
    for metric in BUSINESS_METRICS:
        if asks_diagnosis_scope and metric.name in {"total_partos", "partos_cesarianos"}:
            continue
        metric_tokens = set(metric.trigger_terms)
        if question_tokens & metric_tokens:
            selected.append(metric)
    return selected[:6]


PARTO_PROCEDURE_CODES = (
    ("0310010039", "PARTO NORMAL"),
    ("0310010047", "PARTO NORMAL EM GESTACAO DE ALTO RISCO"),
    ("0310010055", "PARTO NORMAL EM CENTRO DE PARTO NORMAL (CPN)"),
    ("0411010026", "PARTO CESARIANO EM GESTACAO DE ALTO RISCO"),
    ("0411010034", "PARTO CESARIANO"),
    ("0411010042", "PARTO CESARIANO C/ LAQUEADURA TUBARIA"),
)


def _structural_patterns(contract: QuestionContract) -> set[str]:
    patterns = {contract.intent}
    if contract.ranking.n is not None and contract.ranking.partition_by:
        patterns.add("top_n_per_group")
    elif contract.ranking.n is not None:
        patterns.add("top_n")
    if contract.time.grain != "none":
        patterns.add(f"time_{contract.time.grain}")
    return patterns


def rank_query_examples(
    question: str,
    ctx: Stage1Context,
    *,
    contract: QuestionContract | None = None,
    retrieved_tables: list[str] | None = None,
    limit: int = 4,
    minimum_score: float = 2.5,
) -> tuple[list[GroundTruthItem], list[ExampleRetrievalDecision]]:
    contract = contract or build_question_contract(question)
    question_tokens = tokenize(question)
    requested_concepts = set(contract.concepts)
    requested_metrics = {metric.concept for metric in contract.metrics}
    requested_patterns = _structural_patterns(contract)
    requested_tables = set(retrieved_tables or [])
    candidates: list[tuple[float, GroundTruthItem, list[str], list[str]]] = []
    for item in ctx.example_bank:
        example_contract = build_question_contract(item.question_pt)
        example_concepts = set(item.concepts or example_contract.concepts)
        example_metrics = set(
            item.metric_concepts or (metric.concept for metric in example_contract.metrics)
        )
        example_patterns = set(item.structural_patterns or _structural_patterns(example_contract))
        reasons: list[str] = []
        rejection_reasons: list[str] = []

        if "ranking.n" in item.requires_explicit and not contract.ranking.explicit_n:
            rejection_reasons.append("requires_explicit:ranking.n")
        if (
            "ranking.minimum_support" in item.requires_explicit
            and not contract.ranking.explicit_minimum_support
        ):
            rejection_reasons.append("requires_explicit:ranking.minimum_support")
        if (
            "dimensions.age_band.definition" in item.requires_explicit
            and "age_band_definition_unresolved" in contract.ambiguities
        ):
            rejection_reasons.append("requires_explicit:dimensions.age_band.definition")
        blocked = requested_concepts & set(item.forbidden_transfer)
        if blocked:
            rejection_reasons.append(
                "forbidden_transfer:" + ",".join(sorted(blocked))
            )

        score = 0.0
        if contract.intent == example_contract.intent:
            score += 2.0
            reasons.append(f"intent:{contract.intent}")
        concept_overlap = requested_concepts & example_concepts
        if concept_overlap:
            score += 2.5 * len(concept_overlap)
            reasons.append("concepts:" + ",".join(sorted(concept_overlap)))
        metric_overlap = requested_metrics & example_metrics
        if metric_overlap:
            score += 3.0 * len(metric_overlap)
            reasons.append("metrics:" + ",".join(sorted(metric_overlap)))
        pattern_overlap = requested_patterns & example_patterns
        if pattern_overlap:
            score += 1.5 * len(pattern_overlap)
            reasons.append("patterns:" + ",".join(sorted(pattern_overlap)))
        table_overlap = requested_tables & set(item.tables_used)
        if table_overlap:
            score += 0.75 * len(table_overlap)
            reasons.append("tables:" + ",".join(sorted(table_overlap)))

        example_tokens = tokenize(item.question_pt)
        union = question_tokens | example_tokens
        lexical = len(question_tokens & example_tokens) / len(union) if union else 0.0
        score += min(1.5, lexical * 3.0)
        if lexical:
            reasons.append(f"lexical:{lexical:.3f}")

        if score < minimum_score:
            rejection_reasons.append(f"score_below_threshold:{score:.3f}")
        candidates.append((score, item, reasons, rejection_reasons))

    candidates.sort(key=lambda value: (-value[0], value[1].id))
    selected: list[GroundTruthItem] = []
    selected_ids: set[str] = set()
    selected_families: set[str] = set()
    for allow_duplicate_family in (False, True):
        for score, item, _, rejection_reasons in candidates:
            if rejection_reasons or item.id in selected_ids:
                continue
            family = item.template_family or item.id
            if not allow_duplicate_family and family in selected_families:
                continue
            selected.append(item)
            selected_ids.add(item.id)
            selected_families.add(family)
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break

    decisions = [
        ExampleRetrievalDecision(
            example_id=item.id,
            score=round(score, 6),
            accepted=item.id in selected_ids,
            reasons=reasons,
            rejection_reasons=(
                rejection_reasons
                if item.id not in selected_ids
                else []
            ),
        )
        for score, item, reasons, rejection_reasons in candidates
    ]
    return selected, decisions


def retrieve_query_examples(
    question: str,
    ctx: Stage1Context,
    *,
    limit: int = 4,
) -> list[GroundTruthItem]:
    selected, _ = rank_query_examples(question, ctx, limit=limit)
    return selected


def _extract_place_terms(question: str) -> list[str]:
    terms = []
    for match in PLACE_QUERY_RE.finditer(question):
        term = match.group(1).strip(" .,;:!?")
        term = re.sub(r"^(?:cidade|municipio)\s+(?:de|do|da)\s+", "", term, flags=re.I)
        term = re.split(
            r"\s+(?:ao|aos|por|com|acima|abaixo|entre|durante|quando)\b",
            term,
            maxsplit=1,
            flags=re.I,
        )[0].strip(" .,;:!?")
        if term:
            terms.append(term)
    normalized = normalize_text(question)
    for known in ("porto alegre", "sao paulo", "rio de janeiro", "belo horizonte", "santa maria"):
        if known in normalized:
            terms.append(known)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = normalize_text(term)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(term)
    return deduped[:3]


@lru_cache(maxsize=128)
def _query_municipality_hints(db_path: str, term: str) -> tuple[tuple[Any, ...], ...]:
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    try:
        return tuple(
            con.execute(
                """
                SELECT NO_MUNICIPIO, SG_UF
                FROM municipios
                WHERE LOWER(NO_MUNICIPIO) LIKE ?
                ORDER BY NO_MUNICIPIO
                LIMIT 5
                """,
                [f"%{normalize_text(term)}%"],
            ).fetchall()
        )
    finally:
        con.close()


@lru_cache(maxsize=8)
def _query_sex_hints(db_path: str) -> tuple[tuple[Any, ...], ...]:
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    try:
        return tuple(
            con.execute(
                """
                SELECT SEXO, DESCRICAO
                FROM sexo
                ORDER BY SEXO
                LIMIT 10
                """
            ).fetchall()
        )
    finally:
        con.close()


def retrieve_value_hints(
    question: str,
    config: ChatbotConfig | None,
    retrieved: RetrievedContext,
) -> list[ValueHint]:
    hints: list[ValueHint] = []
    normalized = normalize_text(question)

    if "municipios" in retrieved.tables and config is not None and config.db_path.exists():
        for term in _extract_place_terms(question):
            try:
                for municipio, uf in _query_municipality_hints(str(config.db_path), term):
                    hints.append(
                        ValueHint(
                            table="municipios",
                            column="NO_MUNICIPIO",
                            value=municipio,
                            label=str(uf) if uf is not None else "",
                            match_reason=f"matched place term: {term}",
                        )
                    )
            except Exception:
                continue

    if config is not None and config.db_path.exists() and (
        "sexo" in retrieved.tables
        or any(
            token in normalized
            for token in (
                "sexo",
                "homem",
                "homens",
                "masculino",
                "mulher",
                "mulheres",
                "feminino",
            )
        )
    ):
        try:
            for code, description in _query_sex_hints(str(config.db_path)):
                hints.append(
                    ValueHint(
                        table="sexo",
                        column="SEXO",
                        value=code,
                        label=str(description),
                        match_reason="question mentions sex/gender terms",
                    )
                )
        except Exception:
            pass

    if "procedimentos" in retrieved.tables and not mentions_cephalic_delivery(question) and any(
        token in normalized for token in ("parto", "partos", "cesariano", "cesarianos", "cesariana")
    ):
        for code, label in PARTO_PROCEDURE_CODES:
            if "cesar" in normalized and "CESARIANO" not in label:
                continue
            hints.append(
                ValueHint(
                    table="procedimentos",
                    column="PROC_REA",
                    value=code,
                    label=label,
                    match_reason="default childbirth procedure metric",
                )
            )

    return hints[:12]


def retrieve_catalog_candidates(
    question: str,
    config: ChatbotConfig | None,
    retrieved: RetrievedContext,
) -> list[CatalogCandidate]:
    if config is None or not config.catalog_tools_enabled or not config.db_path.exists():
        return []
    try:
        retriever = CatalogRetriever.from_config(config)
    except Exception:
        return []

    candidates: list[CatalogCandidate] = []
    if "cid" in retrieved.tables:
        try:
            result = retriever.search_cid(question, limit=5)
            candidates.extend(result.candidates)
        except Exception:
            pass
    if "procedimentos" in retrieved.tables and (
        not mentions_cephalic_delivery(question) or "procedimento" in normalize_text(question)
    ):
        try:
            result = retriever.search_procedures(question, limit=5)
            candidates.extend(result.candidates)
        except Exception:
            pass
    return candidates[:10]


def enrich_retrieved_context(
    *,
    question: str,
    ctx: Stage1Context,
    retrieved: RetrievedContext,
    config: ChatbotConfig | None = None,
    include_query_examples: bool = True,
) -> RetrievedContext:
    contract = build_question_contract(question)
    rules = applicable_semantic_rules(contract, ctx.semantic_rules)
    contract = contract.model_copy(
        update={"semantic_rule_ids": [rule.id for rule in rules]}
    )
    examples: list[GroundTruthItem] = []
    decisions: list[ExampleRetrievalDecision] = []
    if include_query_examples:
        examples, decisions = rank_query_examples(
            question,
            ctx,
            contract=contract,
            retrieved_tables=retrieved.tables,
        )
    return retrieved.model_copy(
        update={
            "business_metrics": retrieve_metric_context(question),
            "query_examples": examples,
            "example_retrieval_decisions": decisions,
            "question_contract": contract,
            "semantic_rule_ids": [rule.id for rule in rules],
            "semantic_rule_context": [
                f"{rule.id}: concept={rule.concept}; predicate={rule.predicate}; "
                f"source={rule.provenance.type}:{rule.provenance.reference}"
                for rule in rules
            ],
            "assumptions_used": contract.assumptions_used,
            "value_hints": retrieve_value_hints(question, config, retrieved),
            "catalog_candidates": retrieve_catalog_candidates(question, config, retrieved),
        }
    )
