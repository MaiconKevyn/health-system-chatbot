from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .catalogs.models import CatalogCandidate
from .catalogs.retriever import CatalogRetriever
from .config import ChatbotConfig
from .models import BusinessMetric, GroundTruthItem, RetrievedContext, Stage1Context, ValueHint
from .text import normalize_text, tokenize


BUSINESS_METRICS: tuple[BusinessMetric, ...] = (
    BusinessMetric(
        name="total_partos",
        description=(
            "Contagem de partos por procedimento principal realizado na internacao. "
            "Usar esta metrica como padrao para perguntas simples como 'quantos partos aconteceram'."
        ),
        formula=(
            "COUNT(*) FROM internacoes WHERE PROC_REA IN "
            "('0310010039','0310010047','0310010055','0411010026','0411010034','0411010042')"
        ),
        tables=["internacoes", "procedimentos"],
        columns=["internacoes.PROC_REA", "procedimentos.PROC_REA", "procedimentos.NOME_PROC"],
        caveats=[
            "A unidade de analise e internacao/AIH com procedimento principal de parto.",
            "Nao usar DIAG_PRINC LIKE 'O8%' como padrao: O85-O89 inclui complicacoes do puerperio.",
        ],
        trigger_terms=["parto", "partos"],
    ),
    BusinessMetric(
        name="partos_cesarianos",
        description="Contagem de partos cesarianos por procedimento principal realizado.",
        formula=(
            "COUNT(*) FROM internacoes WHERE PROC_REA IN "
            "('0411010026','0411010034','0411010042')"
        ),
        tables=["internacoes", "procedimentos"],
        columns=["internacoes.PROC_REA", "procedimentos.PROC_REA", "procedimentos.NOME_PROC"],
        caveats=["A unidade de analise e internacao/AIH com procedimento principal cesariano."],
        trigger_terms=["cesariano", "cesarianos", "cesariana", "cesarianas"],
    ),
    BusinessMetric(
        name="total_mortes_hospitalares",
        description="Contagem de internacoes/AIH que resultaram em obito hospitalar.",
        formula="COUNT(*) FROM internacoes WHERE internacoes.MORTE = TRUE",
        tables=["internacoes"],
        columns=["internacoes.MORTE"],
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
        formula="COUNT(*) FROM internacoes",
        tables=["internacoes"],
        columns=[],
        caveats=["A unidade de analise e internacao/AIH, nao paciente unico."],
        trigger_terms=["internacao", "internacoes", "aih", "total", "quantas"],
    ),
    BusinessMetric(
        name="taxa_mortalidade_hospitalar",
        description="Taxa bruta de mortalidade hospitalar.",
        formula="100.0 * COUNT(*) FILTER (WHERE internacoes.MORTE) / COUNT(*)",
        tables=["internacoes"],
        columns=["internacoes.MORTE"],
        caveats=["Declarar denominador, periodo e filtros usados."],
        trigger_terms=["mortalidade", "morte", "mortes", "obito", "obitos", "taxa"],
    ),
    BusinessMetric(
        name="valor_total_aprovado",
        description="Valor total aprovado registrado em VAL_TOT.",
        formula="SUM(internacoes.VAL_TOT)",
        tables=["internacoes"],
        columns=["internacoes.VAL_TOT"],
        caveats=["Declarar que a base financeira e VAL_TOT."],
        trigger_terms=["valor", "custo", "financeiro", "aprovado", "val_tot"],
    ),
    BusinessMetric(
        name="permanencia_media",
        description="Media de dias de permanencia hospitalar.",
        formula="AVG(internacoes.DIAS_PERM)",
        tables=["internacoes"],
        columns=["internacoes.DIAS_PERM"],
        caveats=["Verificar qualidade e completude de DIAS_PERM."],
        trigger_terms=["permanencia", "dias", "media"],
    ),
    BusinessMetric(
        name="procedimentos_ocorrencias",
        description="Contagem em internacao_procedimento muda o grao para ocorrencia de procedimento.",
        formula="COUNT(*) FROM internacao_procedimento",
        tables=["internacao_procedimento", "procedimentos"],
        columns=["internacao_procedimento.PROC_REA"],
        caveats=["Nao interpretar COUNT(*) apos join com procedimentos como numero de internacoes."],
        trigger_terms=["procedimento", "procedimentos", "proc_rea", "ocorrencia"],
    ),
    BusinessMetric(
        name="geografia_residencia",
        description="Geografia do usuario/paciente via municipio de residencia.",
        formula="internacoes.MUNIC_RES -> municipios.CO_MUNICIPIO_6D",
        tables=["internacoes", "municipios"],
        columns=["internacoes.MUNIC_RES", "municipios.NO_MUNICIPIO", "municipios.SG_UF"],
        caveats=["Declarar universo mapeado ou usar LEFT JOIN com bucket sem correspondencia."],
        trigger_terms=["residencia", "residentes", "moradores", "municipio", "uf"],
    ),
    BusinessMetric(
        name="geografia_hospital",
        description="Geografia do estabelecimento/hospital via municipio do atendimento.",
        formula="hospital.MUNIC_MOV -> municipios.CO_MUNICIPIO_6D",
        tables=["hospital", "municipios"],
        columns=["hospital.MUNIC_MOV", "municipios.NO_MUNICIPIO", "municipios.SG_UF"],
        caveats=["Nao confundir municipio do hospital com municipio de residencia."],
        trigger_terms=["hospital", "hospitais", "estabelecimento", "atendimento", "local"],
    ),
)


PLACE_QUERY_RE = re.compile(
    r"\b(?:em|de|do|da|no|na)\s+([A-Za-z][A-Za-z -]{2,40})"
)


def retrieve_metric_context(question: str) -> list[BusinessMetric]:
    question_tokens = tokenize(question)
    normalized = normalize_text(question)
    asks_diagnosis_scope = (
        "diagnostico" in normalized
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


def retrieve_query_examples(
    question: str,
    ctx: Stage1Context,
    *,
    limit: int = 4,
) -> list[GroundTruthItem]:
    question_tokens = tokenize(question)
    scored: list[tuple[float, GroundTruthItem]] = []
    for item in ctx.ground_truth:
        haystack = " ".join(
            [
                item.question_pt,
                item.sql,
                " ".join(item.tables_used),
                " ".join(item.columns_used),
                item.expected_result_type or "",
                item.result_summary or "",
                item.data_quality_notes or "",
            ]
        )
        hay_tokens = tokenize(haystack)
        overlap = len(question_tokens & hay_tokens)
        table_bonus = 0.5 * len(question_tokens & set(item.tables_used))
        score = overlap + table_bonus
        normalized_question = normalize_text(question)
        normalized_haystack = normalize_text(haystack)
        if ("parto" in normalized_question or "partos" in normalized_question) and (
            "parto" in normalized_haystack or "partos" in normalized_haystack
        ):
            score += 5.0
        if "cesarian" in normalized_question and "cesarian" in normalized_haystack:
            score += 5.0
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]


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

    if "procedimentos" in retrieved.tables and any(
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
    if "procedimentos" in retrieved.tables:
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
) -> RetrievedContext:
    return retrieved.model_copy(
        update={
            "business_metrics": retrieve_metric_context(question),
            "query_examples": retrieve_query_examples(question, ctx),
            "value_hints": retrieve_value_hints(question, config, retrieved),
            "catalog_candidates": retrieve_catalog_candidates(question, config, retrieved),
        }
    )
