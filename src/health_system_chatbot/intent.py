from __future__ import annotations

from .models import QuestionIntent, Stage1Context
from .text import normalize_text


OUT_OF_SCOPE_TERMS = {
    "previsao do tempo",
    "cotacao",
    "bolsa",
    "futebol",
    "receita culinaria",
}


def classify_question(question: str, ctx: Stage1Context | None = None) -> QuestionIntent:
    normalized = normalize_text(question)
    tokens = set(normalized.split())
    ambiguities: list[str] = []
    caveats: list[str] = []

    if not normalized:
        return QuestionIntent(
            status="needs_clarification",
            reason="Pergunta vazia.",
            normalized_question=normalized,
            ambiguities=["pergunta_vazia"],
        )

    if any(term in normalized for term in OUT_OF_SCOPE_TERMS):
        return QuestionIntent(
            status="refused",
            reason="Pergunta fora do escopo do banco SIH/SUS local.",
            normalized_question=normalized,
        )

    if "paciente" in normalized and ("unico" in normalized or "distinto" in normalized):
        return QuestionIntent(
            status="refused",
            reason="A Stage 1 nao documentou identificador confiavel de paciente unico.",
            normalized_question=normalized,
            required_caveats=["Nao ha identificador confiavel de paciente unico documentado."],
        )

    if "custo" in normalized and not any(
        token in normalized
        for token in ("val_tot", "val_sh", "val_sp", "val_uti", "valor total", "aprovado")
    ):
        ambiguities.append("Definir se custo significa VAL_TOT, VAL_SH, VAL_SP, VAL_UTI ou outra metrica.")

    if "producao" in normalized and not any(
        token in normalized for token in ("internacao", "procedimento", "valor", "aih")
    ):
        ambiguities.append("Definir se producao significa internacoes, procedimentos, AIHs ou valor.")

    if (
        "contraceptivo" in normalized
        and "catalogo" not in normalized
        and "tipo" not in tokens
        and "tipos" not in tokens
        and not any(
        term in normalized
        for term in (
            "contraceptivo 1",
            "contraceptivo 2",
            "contracep1",
            "contracep2",
            "codigo",
            "valor",
            "igual",
        )
        )
    ):
        ambiguities.append(
            "Definir se contraceptivo se refere a coluna CONTRACEP1, CONTRACEP2 ou a um valor/codigo especifico."
        )

    if "local" in normalized and not any(
        token in normalized
        for token in (
            "residencia",
            "hospital",
            "estabelecimento",
            "municipio de residencia",
            "municipio do hospital",
            "uf de residencia",
            "uf do estabelecimento",
        )
    ):
        ambiguities.append("Definir se local e residencia do usuario ou local do hospital.")

    if "mortalidade" in normalized and not any(
        token in normalized
        for token in (
            "taxa",
            "taxa bruta",
            "mortes por internacoes",
            "por ano",
            "hospitalar",
            "pelo menos",
        )
    ):
        ambiguities.append("Definir denominador e periodo da mortalidade.")

    if "residencia" in normalized or "munic_res" in normalized:
        caveats.append("Usar internacoes.MUNIC_RES e declarar universo mapeado quando houver join com municipios.")
    if "hospital" in tokens or "hospitais" in tokens or "estabelecimento" in tokens:
        caveats.append("Usar hospital.MUNIC_MOV para geografia do estabelecimento.")
    if "procedimento" in normalized:
        caveats.append("Ao juntar procedimentos, a unidade pode virar ocorrencia de procedimento.")
    if "valor" in normalized or "custo" in normalized:
        caveats.append("Declarar qual coluna financeira fundamenta a resposta.")

    if ambiguities:
        return QuestionIntent(
            status="needs_clarification",
            reason="Pergunta contem termo ambiguo para a semantica documentada.",
            normalized_question=normalized,
            ambiguities=ambiguities,
            required_caveats=caveats,
        )

    return QuestionIntent(
        status="answerable",
        reason="Pergunta dentro do escopo documentado.",
        normalized_question=normalized,
        required_caveats=caveats,
    )
