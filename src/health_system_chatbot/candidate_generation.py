from __future__ import annotations

from .config import ChatbotConfig
from .models import RetrievedContext, SqlPlan, Stage1Context
from .sql_generator import generate_sql_plan


CANDIDATE_HINTS: tuple[str, ...] = (
    (
        "Gere a candidata principal priorizando a interpretacao direta da pergunta, "
        "com o menor numero de joins necessario."
    ),
    (
        "Gere uma alternativa verificando se alguma dimensao, value hint ou regra "
        "de negocio recuperada muda filtros, joins ou grao."
    ),
    (
        "Gere uma alternativa conservadora: prefira agregacoes explicitas, aliases "
        "claros e caveats quando houver ambiguidade de geografia, data ou metrica."
    ),
)


def should_use_multi_candidate(config: ChatbotConfig, *, allow_llm: bool) -> bool:
    return (
        allow_llm
        and config.agent_framework == "pydantic_ai"
        and config.enable_multi_candidate
        and config.sql_candidates > 1
    )


def _candidate_hint(index: int) -> str:
    if index < len(CANDIDATE_HINTS):
        return CANDIDATE_HINTS[index]
    return (
        "Gere uma alternativa adicional semanticamente distinta quando isso for "
        "justificado pelo contexto; se nao houver distincao real, preserve a query "
        "mais correta."
    )


def generate_sql_candidates(
    question: str,
    context: RetrievedContext,
    stage1_context: Stage1Context,
    config: ChatbotConfig,
    *,
    allow_llm: bool = True,
) -> list[SqlPlan]:
    count = max(1, config.sql_candidates)
    candidates: list[SqlPlan] = []
    for index in range(count):
        plan = generate_sql_plan(
            question,
            context,
            stage1_context,
            config,
            allow_llm=allow_llm,
            generation_hint=_candidate_hint(index),
        )
        plan.source = f"{plan.source}:candidate_{index + 1}"
        candidates.append(plan)
    return candidates
