from __future__ import annotations

import re
import unicodedata

from .schema import ChartType, VisualizationIntent


_CHART_HINT_PATTERNS: tuple[tuple[str, ChartType], ...] = (
    (r"\bgrafico\s+de\s+barras?\b|\bgrafico\s+de\s+colunas?\b|\bbar\s+chart\b", "bar"),
    (r"\bgrafico\s+de\s+linhas?\b|\bline\s+chart\b|\blinha\s+temporal\b", "line"),
    (r"\bgrafico\s+de\s+area\b|\barea\s+chart\b", "area"),
    (r"\bgrafico\s+de\s+pizza\b|\bpizza\b|\bpie\s+chart\b", "pie"),
    (r"\bgrafico\s+de\s+rosca\b|\bdonut\b|\brosca\b", "donut"),
    (r"\bscatter\b|\bdispersao\b|\bdispersao\b", "scatter"),
    (r"\bkpi\b|\bindicador\b|\bcard\b", "kpi"),
)

_EXPLICIT_CHART_TERMS = (
    "grafico",
    "graficos",
    "visualizacao",
    "visualizar em grafico",
    "visualize em grafico",
    "mostre em grafico",
    "mostrar em grafico",
    "gere um grafico",
    "gerar um grafico",
    "crie um grafico",
    "criar um grafico",
    "plot",
    "plotar",
    "plote",
    "chart",
    "bar chart",
    "line chart",
    "pie chart",
    "donut chart",
    "scatter plot",
    "linha temporal",
)

_META_CHART_PHRASES = (
    "ideias de grafico",
    "ideias de graficos",
    "que tipo de grafico",
    "que tipos de grafico",
    "quais graficos",
    "exemplos de grafico",
    "exemplos de graficos",
    "sugestoes de grafico",
    "sugestoes de graficos",
    "sugira graficos",
    "sugira um grafico",
    "chart ideas",
    "what charts",
)

_FOLLOWUP_REFERENCES = (
    "disso",
    "dessa resposta",
    "essa resposta",
    "resultado anterior",
    "ultimo resultado",
    "ultima resposta",
    "esses dados",
    "esses resultados",
    "isso",
)

_CHART_COMMAND_PATTERNS = (
    r"\b(?:gere|gerar|crie|criar|mostre|mostrar|visualize|visualizar|plote|plotar)\s+(?:um|uma|o|a|em)?\s*grafico(?:\s+de\s+\w+)?\s+(?:com|da|de|do|das|dos|sobre|para)?\s*",
    r"\bgrafico\s+de\s+(?:barras?|colunas?|linhas?|pizza|rosca|area|dispersao)\s+(?:com|da|de|do|das|dos|sobre|para)?\s*",
    r"\bem\s+grafico\b",
    r"\bvisualizacao\s+(?:de|da|do|das|dos)?\s*",
    r"\b(?:bar|line|pie|donut|scatter)\s+chart\s+(?:of|for|de|da|do)?\s*",
)


def normalize_visual_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _detect_chart_hint(normalized_query: str) -> ChartType:
    for pattern, chart_type in _CHART_HINT_PATTERNS:
        if re.search(pattern, normalized_query):
            return chart_type
    return "auto"


def _analysis_question(original: str) -> str:
    text = normalize_visual_text(original)
    for pattern in _CHART_COMMAND_PATTERNS:
        text = re.sub(pattern, " ", text)
    text = re.sub(
        r"\b(?:grafico|graficos|chart|plot|plotar|plote|visualizacao|visualizar)\b",
        " ",
        text,
    )
    text = re.sub(r"\b(?:de\s+)?(?:barras?|colunas?|linhas?|pizza|rosca|area|dispersao)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    return text or original.strip()


def detect_visualization_intent(user_query: str) -> VisualizationIntent:
    normalized = normalize_visual_text(user_query)
    if not normalized:
        return VisualizationIntent(requested=False, analysis_question="")
    if any(phrase in normalized for phrase in _META_CHART_PHRASES):
        return VisualizationIntent(requested=False, analysis_question=user_query.strip())

    requested = any(term in normalized for term in _EXPLICIT_CHART_TERMS)
    if not requested:
        return VisualizationIntent(requested=False, analysis_question=user_query.strip())

    chart_hint = _detect_chart_hint(normalized)
    uses_last_result = any(reference in normalized for reference in _FOLLOWUP_REFERENCES)
    source = "explicit_followup" if uses_last_result else "explicit_current_query"
    reason = (
        f"Usuario pediu explicitamente grafico do tipo {chart_hint}"
        if chart_hint != "auto"
        else "Usuario pediu explicitamente visualizacao em grafico"
    )
    return VisualizationIntent(
        requested=True,
        source=source,
        uses_last_result=uses_last_result,
        chart_hint=chart_hint,
        analysis_question=_analysis_question(user_query),
        reason=reason,
    )

