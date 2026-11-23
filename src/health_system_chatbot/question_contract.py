from __future__ import annotations

import re

from .models import (
    OutputContract,
    QuestionContract,
    QuestionDimension,
    QuestionMetric,
    RankingContract,
    TimeContract,
)
from .text import normalize_text


_DIMENSION_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("state", ("estado", "estados", "uf", "ufs")),
    ("municipality", ("municipio", "municipios", "cidade", "cidades")),
    ("hospital", ("hospital", "hospitais", "cnes")),
    ("sex", ("sexo", "masculino", "feminino", "homens", "mulheres")),
    ("age_band", ("faixa etaria", "faixas etarias")),
    ("medical_specialty", ("especialidade", "especialidades")),
    ("procedure", ("procedimento", "procedimentos")),
    ("education_level", ("instrucao", "escolaridade")),
    ("weekday", ("dia da semana",)),
)

_PARTITION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("state", ("por estado", "por uf", "em cada estado", "em cada uf")),
    ("municipality", ("por municipio", "em cada municipio")),
    ("sex", ("por sexo", "em cada sexo", "para cada sexo")),
    ("age_band", ("por faixa etaria", "em cada faixa etaria", "para cada faixa etaria")),
    ("medical_specialty", ("por especialidade", "em cada especialidade")),
    ("diagnosis_chapter", ("por capitulo", "em cada capitulo", "para cada capitulo")),
)


_QUANTITY_OF_YEARS_RE = re.compile(r"\b\d+\s+anos\b")
_CEPHALIC_DELIVERY_RE = re.compile(r"\bpartos? (?:unicos? )?espontaneos? cefalicos?\b")
_CARE_LOCATION_RE = re.compile(
    r"\b(?:feit[oa]s?|realizad[oa]s?|ocorrid[oa]s?) (?:no|na|em) "
    r"(?:estado|municipio|cidade|distrito federal|acre|alagoas|amapa|amazonas|bahia|ceara|"
    r"espirito santo|goias|maranhao|mato grosso|minas gerais|para|paraiba|parana|pernambuco|"
    r"piaui|rio de janeiro|rio grande do norte|rio grande do sul|rondonia|roraima|santa catarina|"
    r"sao paulo|sergipe|tocantins|ac|al|ap|am|ba|ce|df|es|go|ma|mt|ms|mg|pa|pb|pr|pe|pi|"
    r"rj|rn|rs|ro|rr|sc|sp|se|to)\b"
)


def mentions_cephalic_delivery(question: str) -> bool:
    return bool(_CEPHALIC_DELIVERY_RE.search(normalize_text(question)))


def mentions_care_location(question: str) -> bool:
    return bool(_CARE_LOCATION_RE.search(normalize_text(question)))


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _mentions_years_as_period(text: str) -> bool:
    # "60 anos" / "ultimos 5 anos" is an age or a duration, never a per-year grain.
    return re.search(r"\banos\b", _QUANTITY_OF_YEARS_RE.sub(" ", text)) is not None


def _intent(text: str) -> str:
    if _contains_any(text, ("evolucao", "serie", "ao longo", "media movel")):
        return "time_series"
    if _contains_any(text, ("compara", "comparacao", "diferenca", "razao", "aumento", "queda")):
        return "comparison"
    if _contains_any(text, ("distribuicao", "se distribuem", "percentual por")):
        return "distribution"
    if _contains_any(text, ("quais", "maior", "maiores", "mais frequente", "principais", "top")):
        return "ranking"
    if _contains_any(text, ("qual", "quantas", "quantos", "total", "taxa")):
        return "scalar"
    return "other"


def _explicit_number(text: str) -> int | None:
    patterns = (
        r"\btop\s*-?\s*(\d+)\b",
        r"\b(?:os|as)?\s*(\d+)\s+(?:principais|maiores|menores|cnes|municipios|hospitais|diagnosticos|procedimentos)\b",
        r"\bquais\s+(?:sao\s+)?(?:os|as)\s+(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    # A singular superlative is an explicit request for one result.  This is a
    # linguistic property of the question, not a benchmark-specific default.
    if re.search(
        r"\b(?:qual|em qual)\b.*\b(?:o|a)\s+(?:maior|menor|mais frequente|menos frequente)\b",
        text,
    ):
        return 1
    return None


def _minimum_support(text: str) -> int | None:
    match = re.search(
        r"\b(?:mais de|pelo menos|no minimo|minimo de)\s+(\d+)\s+(?:internacoes|casos|registros|obitos)\b",
        text,
    )
    return int(match.group(1)) if match else None


def _time_contract(text: str) -> TimeContract:
    grain = "none"
    if "dia da semana" in text or re.search(r"\bpor dia\b", text):
        grain = "day"
    elif "semana" in text:
        grain = "week"
    elif _contains_any(text, ("mensal", "por mes", "cada mes")):
        grain = "month"
    elif _contains_any(text, ("trimestre", "trimestral")):
        grain = "quarter"
    elif re.search(r"\b(?:anual|anuais|por ano|cada ano)\b", text) or _mentions_years_as_period(text):
        grain = "year"

    basis = "none"
    if _contains_any(text, ("dt_inter", "data de internacao", "data de entrada", "admissao")):
        basis = "admission_date"
    elif _contains_any(text, ("dt_saida", "data de saida", "data de alta")):
        basis = "discharge_date"
    elif grain != "none" or re.search(r"\b(?:19|20)\d{2}\b", text):
        # A hospitalization/admission occurring in a period is anchored by its
        # admission date by the ordinary meaning of the event.  Outcome-only
        # questions (for example mortality "in 2021") remain unresolved.
        basis = (
            "admission_date"
            if _contains_any(text, ("internacao", "internacoes", "admissao", "admissoes"))
            else "unresolved"
        )

    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", text)]
    return TimeContract(
        basis=basis,
        grain=grain,
        start_year=min(years) if years else None,
        end_year=max(years) if years else None,
        explicit_in_question=bool(years or grain != "none"),
    )


def build_question_contract(question: str) -> QuestionContract:
    """Extract only semantics supported by the question text.

    The extractor deliberately leaves material conventions unresolved instead of
    learning defaults from evaluation SQL or retrieved examples.
    """

    text = normalize_text(question)
    intent = _intent(text)
    concepts: list[str] = []
    dimensions: list[QuestionDimension] = []
    metrics: list[QuestionMetric] = []
    ambiguities: list[str] = []
    required_sources: list[str] = []

    for concept, terms in _DIMENSION_TERMS:
        if _contains_any(text, terms):
            dimensions.append(
                QuestionDimension(concept=concept, explicit_in_question=True)
            )
            concepts.append(concept)

    if "capitulo" in text and "cid" in text:
        dimensions.append(QuestionDimension(concept="diagnosis_chapter", explicit_in_question=True))
        concepts.append("diagnosis_chapter")
    elif "grupo" in text and "cid" in text:
        dimensions.append(QuestionDimension(concept="diagnosis_group", explicit_in_question=True))
        concepts.append("diagnosis_group")
    elif "cid" in text:
        dimensions.append(QuestionDimension(concept="diagnosis_code", explicit_in_question=True))
        concepts.append("diagnosis_code")
    elif "diagnostico" in text or "motivo" in text:
        dimensions.append(
            QuestionDimension(concept="diagnosis_description", explicit_in_question=True)
        )
        concepts.append("diagnosis_description")

    if _contains_any(text, ("mortalidade", "taxa de morte", "taxa de obito")):
        metrics.append(
            QuestionMetric(
                concept="mortality_rate",
                numerator="deaths",
                denominator="admissions",
                unit="percent",
            )
        )
        concepts.append("mortality_rate")
    if _contains_any(text, ("internacoes", "internacao", "aih")):
        metrics.append(QuestionMetric(concept="admissions"))
        concepts.append("admissions")
    if _contains_any(text, ("custo medio de uti", "val_uti", "custo de uti")):
        metrics.append(QuestionMetric(concept="positive_uti_cost", unit="currency"))
        concepts.append("positive_uti_cost")
    elif "uti" in text:
        metrics.append(QuestionMetric(concept="uti_usage"))
        concepts.append("uti_usage")
    if _contains_any(text, ("indigena", "indigenas")):
        concepts.append("indigenous_population")
    if _contains_any(text, ("covid", "coronavirus")):
        concepts.append("covid_admissions")
    if mentions_cephalic_delivery(text):
        concepts.append("spontaneous_cephalic_delivery")
    if mentions_care_location(text):
        concepts.append("care_location")
    if _contains_any(text, ("obstetrica", "obstetrico", "obstetricas", "obstetricos")):
        concepts.append("obstetric_population")
        ambiguities.append("obstetric_population_definition_unresolved")
    if _contains_any(text, ("diagnostico secundario", "diagnosticos secundarios")):
        concepts.append("secondary_diagnosis")
        ambiguities.append("secondary_diagnosis_definition_unresolved")
    if re.search(r"\b(.+?)\s+e\s+nao\s+\1\b", text):
        concepts.append("complementary_partition")
    if _contains_any(text, ("populacao", "por mil habitantes", "pib per capita", "leitos sus")):
        required_sources.append("socioeconomico")
        concepts.append("socioeconomic_denominator")
    if _contains_any(text, ("auditoria", "sem correspondencia", "nao mapeado", "orfa")):
        concepts.append("dimension_coverage_audit")
    cumulative_threshold_percent = None
    if _contains_any(text, ("cobrem", "cobre", "acumulad", "cumulativ")):
        concepts.append("cumulative_coverage")
        threshold_match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*%", text)
        if threshold_match:
            cumulative_threshold_percent = float(
                threshold_match.group(1).replace(",", ".")
            )

    if any(d.concept == "age_band" for d in dimensions):
        numeric_cuts = re.findall(r"\b\d+\b", text)
        if not numeric_cuts:
            ambiguities.append("age_band_definition_unresolved")
    time = _time_contract(text)
    if time.basis == "unresolved":
        ambiguities.append("date_basis_unresolved")

    n = _explicit_number(text)
    minimum_support = _minimum_support(text)
    partition_by = [
        concept
        for concept, patterns in _PARTITION_PATTERNS
        if _contains_any(text, patterns)
    ]
    # Explicitly enumerated age cohorts in a ranking request mean that the
    # requested N applies to each cohort.  Merely mentioning ages does not.
    if (
        intent == "ranking"
        and "age_band" not in partition_by
        and len(re.findall(r"\b\d+\b", text)) >= 2
        and _contains_any(text, ("ano de idade", "anos", "idade", "faixa etaria"))
        and _contains_any(text, ("menos de", "entre", "acima de", "mais de"))
    ):
        partition_by.append("age_band")
    ranking = RankingContract(
        n=n,
        partition_by=partition_by,
        minimum_support=minimum_support,
        explicit_n=n is not None,
        explicit_minimum_support=minimum_support is not None,
    )

    output_required = list(dict.fromkeys([d.concept for d in dimensions] + [m.concept for m in metrics]))
    if "dimension_coverage_audit" in concepts:
        output_required.extend(["unmatched_count", "total_count"])
    output = OutputContract(
        required_concepts=output_required,
        representation="any",
        ordering="required" if intent == "ranking" and n is not None else "irrelevant",
    )
    return QuestionContract(
        intent=intent,
        population=text,
        concepts=list(dict.fromkeys(concepts)),
        dimensions=dimensions,
        metrics=metrics,
        time=time,
        ranking=ranking,
        output=output,
        required_sources=list(dict.fromkeys(required_sources)),
        ambiguities=list(dict.fromkeys(ambiguities)),
        cumulative_threshold_percent=cumulative_threshold_percent,
    )
