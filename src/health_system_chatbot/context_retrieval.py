from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

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
    asks_diagnosis_scope = "diagnostico" in normalized or "cid" in normalized
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

CID_LOOKUP_STOPWORDS = {
    "acima",
    "abaixo",
    "aconteceram",
    "aconteceu",
    "anos",
    "ano",
    "cidade",
    "codigo",
    "codigos",
    "com",
    "como",
    "diagnostico",
    "diagnosticos",
    "estado",
    "hospital",
    "hospitalar",
    "internacao",
    "internacoes",
    "mulher",
    "mulheres",
    "morte",
    "mortes",
    "morreu",
    "morreram",
    "municipio",
    "obito",
    "obitos",
    "por",
    "principal",
    "quantas",
    "quantos",
    "total",
}

CID_LOOKUP_ALIASES: dict[str, tuple[str, ...]] = {
    "cancer": ("neopl",),
    "neoplasia": ("neopl",),
    "neoplasias": ("neopl",),
    "tumor": ("neopl",),
    "tumores": ("neopl",),
    "parto": ("parto",),
    "partos": ("parto",),
    "cesariana": ("cesar",),
    "cesarianas": ("cesar",),
    "cesariano": ("cesar",),
    "cesarianos": ("cesar",),
    "infeccao": ("infecc",),
    "infeccoes": ("infecc",),
    "infecciosa": ("infecc",),
    "infecciosas": ("infecc",),
    "infeccioso": ("infecc",),
    "infecciosos": ("infecc",),
}

CID_CHAPTER_LOOKUP_TERMS = {"infecc", "neopl", "parasit"}


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


@lru_cache(maxsize=8)
def _query_cid_cancer_hints(db_path: str) -> tuple[tuple[Any, ...], ...]:
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    try:
        return tuple(
            con.execute(
                """
                SELECT CID, DESCRICAO, DS_CAPITULO
                FROM cid
                WHERE CID LIKE 'C%'
                ORDER BY CID
                LIMIT 5
                """
            ).fetchall()
        )
    finally:
        con.close()


def _extract_cid_lookup_terms(question: str) -> tuple[str, ...]:
    normalized = normalize_text(question)
    terms: list[str] = []
    for trigger, variants in CID_LOOKUP_ALIASES.items():
        if trigger in normalized:
            terms.extend(variants)

    for token in tokenize(question):
        if token in CID_LOOKUP_STOPWORDS or token.startswith("cid"):
            continue
        terms.append(token)
        if token.endswith("s") and len(token) > 5:
            terms.append(token[:-1])

    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = normalize_text(term)
        if len(key) < 4 or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return tuple(deduped[:6])


def _cid_group_tail(group: str) -> str:
    tail = re.sub(r"^[A-Z][0-9]{2}(?:-[A-Z]?[0-9]{2})?\s+", "", group.strip(), flags=re.I)
    return normalize_text(tail)


def _update_best(
    best: dict[str, tuple[int, str, str, str, str]],
    key: str,
    candidate: tuple[int, str, str, str, str],
) -> None:
    current = best.get(key)
    if current is None or candidate[0] > current[0]:
        best[key] = candidate


@lru_cache(maxsize=256)
def _query_cid_lookup_hints(
    db_path: str,
    terms: tuple[str, ...],
) -> tuple[tuple[str, Any, str, str], ...]:
    if not terms:
        return tuple()

    import duckdb

    conditions: list[str] = []
    params: list[str] = []
    for term in terms:
        like = f"%{term}%"
        columns = ["LOWER(CID)", "LOWER(DESCRICAO)", "LOWER(DS_CATEGORIA)", "LOWER(DS_GRUPO)"]
        if term in CID_CHAPTER_LOOKUP_TERMS:
            columns.append("LOWER(DS_CAPITULO)")
        conditions.append("(" + " OR ".join(f"{column} LIKE ?" for column in columns) + ")")
        params.extend([like] * len(columns))

    con = duckdb.connect(db_path, read_only=True)
    try:
        rows = con.execute(
            f"""
            SELECT CID, DESCRICAO, DS_CATEGORIA, DS_GRUPO, DS_CAPITULO
            FROM cid
            WHERE {" OR ".join(conditions)}
            ORDER BY CID
            LIMIT 250
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    chapters: dict[str, tuple[int, str, str, str, str]] = {}
    groups: dict[str, tuple[int, str, str, str, str]] = {}
    codes: dict[str, tuple[int, str, str, str, str]] = {}
    for cid, description, category, group, chapter in rows:
        cid_text = str(cid or "")
        description_text = str(description or "")
        category_text = str(category or "")
        group_text = str(group or "")
        chapter_text = str(chapter or "")
        normalized_fields = {
            "cid": normalize_text(cid_text),
            "description": normalize_text(description_text),
            "category": normalize_text(category_text),
            "group": normalize_text(group_text),
            "chapter": normalize_text(chapter_text),
        }
        for term in terms:
            if term in CID_CHAPTER_LOOKUP_TERMS and term in normalized_fields["chapter"]:
                score = 70
                _update_best(
                    chapters,
                    chapter_text,
                    (score, cid_text, description_text, chapter_text, term),
                )
            if group_text and term in normalized_fields["group"]:
                score = 80
                if _cid_group_tail(group_text) == term:
                    score += 40
                _update_best(
                    groups,
                    group_text,
                    (score, cid_text, description_text, chapter_text, term),
                )
            if (
                term in normalized_fields["cid"]
                or term in normalized_fields["description"]
                or term in normalized_fields["category"]
            ):
                score = 40
                if term in normalized_fields["category"]:
                    score += 10
                if term in normalized_fields["cid"]:
                    score += 30
                _update_best(
                    codes,
                    cid_text,
                    (score, cid_text, description_text, chapter_text, term),
                )

    hints: list[tuple[str, Any, str, str]] = []
    for chapter, (_, cid, description, _, term) in sorted(
        chapters.items(),
        key=lambda item: (-item[1][0], item[0]),
    )[:2]:
        hints.append(
            (
                "DS_CAPITULO",
                chapter,
                f"exemplo={cid} {description}",
                f"CID lookup term: {term}",
            )
        )
    for group, (_, cid, description, chapter, term) in sorted(
        groups.items(),
        key=lambda item: (-item[1][0], item[0]),
    )[:6]:
        hints.append(
            (
                "DS_GRUPO",
                group,
                f"exemplo={cid} {description}; capitulo={chapter}",
                f"CID lookup term: {term}",
            )
        )
    for cid, (_, _, description, chapter, term) in sorted(
        codes.items(),
        key=lambda item: (-item[1][0], item[0]),
    )[:4]:
        hints.append(
            (
                "CID",
                cid,
                f"{description}; capitulo={chapter}",
                f"CID lookup term: {term}",
            )
        )
    return tuple(hints[:8])


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

    if (
        "cid" in retrieved.tables
        and config is not None
        and config.db_path.exists()
        and any(token in normalized for token in ("cid c", "cid-c", "cancer", "neoplasia"))
    ):
        try:
            for cid, description, chapter in _query_cid_cancer_hints(str(config.db_path)):
                hints.append(
                    ValueHint(
                        table="cid",
                        column="CID",
                        value=cid,
                        label=f"{description}; capitulo={chapter}",
                        match_reason="question mentions CID C/cancer/neoplasia",
                    )
                )
        except Exception:
            pass

    if "cid" in retrieved.tables and config is not None and config.db_path.exists():
        try:
            for column, value, label, match_reason in _query_cid_lookup_hints(
                str(config.db_path),
                _extract_cid_lookup_terms(question),
            ):
                hints.append(
                    ValueHint(
                        table="cid",
                        column=column,
                        value=value,
                        label=label,
                        match_reason=match_reason,
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
        }
    )
