from __future__ import annotations

from dataclasses import dataclass

from .text import normalize_text


@dataclass(frozen=True)
class SchemaLink:
    fact_column: str
    dimension_key: str
    description_column: str
    business_name: str
    triggers: tuple[str, ...]

    @property
    def fact_table(self) -> str:
        return self.fact_column.split(".")[0]

    @property
    def dimension_table(self) -> str:
        return self.dimension_key.split(".")[0]

    @property
    def fact_column_name(self) -> str:
        return self.fact_column.split(".")[-1]

    @property
    def description_column_name(self) -> str:
        return self.description_column.split(".")[-1].split("/")[0]


DIMENSION_LINKS: tuple[SchemaLink, ...] = (
    SchemaLink(
        "_staging_internacoes.CAR_INT",
        "car_int.CAR_INT",
        "car_int.DESCRICAO",
        "carater de internacao na staging",
        ("staging", "carater", "car_int", "urgencia", "eletivo"),
    ),
    SchemaLink(
        "internacoes.CAR_INT",
        "car_int.CAR_INT",
        "car_int.DESCRICAO",
        "carater de internacao",
        ("carater", "car_int", "urgencia", "eletivo"),
    ),
    SchemaLink(
        "internacoes.COMPLEX",
        "complexidade.COMPLEX",
        "complexidade.DESCRICAO",
        "complexidade",
        ("complexidade", "complex"),
    ),
    SchemaLink(
        "internacoes.MARCA_UTI",
        "marca_uti.MARCA_UTI",
        "marca_uti.DESCRICAO",
        "marca de UTI",
        ("marca uti", "uti", "marcauti"),
    ),
    SchemaLink(
        "internacoes.SEXO",
        "sexo.SEXO",
        "sexo.DESCRICAO",
        "sexo",
        ("sexo", "masculino", "feminino", "homem", "mulher"),
    ),
    SchemaLink(
        "internacoes.RACA_COR",
        "raca_cor.RACA_COR",
        "raca_cor.DESCRICAO",
        "raca/cor",
        ("raca", "cor", "raca cor"),
    ),
    SchemaLink(
        "internacoes.INSTRU",
        "instrucao.INSTRU",
        "instrucao.DESCRICAO",
        "instrucao",
        ("instrucao", "escolaridade"),
    ),
    SchemaLink(
        "internacoes.VINCPREV",
        "vincprev.VINCPREV",
        "vincprev.DESCRICAO",
        "vinculo previdenciario",
        ("vinculo", "previdenciario", "vincprev"),
    ),
    SchemaLink(
        "internacoes.CBOR",
        "cbor.CBOR",
        "cbor.DESCRICAO",
        "ocupacao/CBOR",
        ("cbor", "ocupacao", "ocupacional"),
    ),
    SchemaLink(
        "internacoes.ETNIA",
        "etnia.ETNIA",
        "etnia.DESCRICAO",
        "etnia",
        ("etnia", "indigena"),
    ),
    SchemaLink(
        "internacoes.NACIONAL",
        "nacionalidade.NACIONAL",
        "nacionalidade.DESCRICAO",
        "nacionalidade",
        ("nacionalidade", "nacionalidades"),
    ),
    SchemaLink(
        "internacoes.CONTRACEP1",
        "contraceptivos.CONTRACEPTIVO",
        "contraceptivos.DESCRICAO",
        "contraceptivo 1",
        ("contraceptivo 1", "contracep1"),
    ),
    SchemaLink(
        "internacoes.CONTRACEP2",
        "contraceptivos.CONTRACEPTIVO",
        "contraceptivos.DESCRICAO",
        "contraceptivo 2",
        ("contraceptivo 2", "contracep2"),
    ),
    SchemaLink(
        "internacoes.DIAG_PRINC",
        "cid.CID",
        "cid.DESCRICAO",
        "diagnostico principal",
        (
            "diagnostico",
            "cid",
            "cancer",
            "neoplasia",
            "infecc",
            "doenca",
            "doencas",
            "causa",
            "causas",
        ),
    ),
    SchemaLink(
        "internacoes.PROC_REA",
        "procedimentos.PROC_REA",
        "procedimentos.NOME_PROC",
        "procedimento principal",
        ("procedimento principal", "procedimentos principais", "proc_rea"),
    ),
    SchemaLink(
        "internacoes.MUNIC_RES",
        "municipios.CO_MUNICIPIO_6D",
        "municipios.NO_MUNICIPIO/municipios.SG_UF",
        "municipio de residencia",
        ("municipio", "residencia", "uf"),
    ),
)


CODE_TERMS = {"codigo", "codigos", "cod", "cods"}


def asks_for_raw_code(question: str) -> bool:
    tokens = set(normalize_text(question).split())
    return bool(tokens & CODE_TERMS)


def question_matches_link(question: str, link: SchemaLink) -> bool:
    text = normalize_text(question)
    return any(trigger in text for trigger in link.triggers)


def links_for_question(question: str) -> list[SchemaLink]:
    return [link for link in DIMENSION_LINKS if question_matches_link(question, link)]


def description_required_for_link(question: str, link: SchemaLink) -> bool:
    if asks_for_raw_code(question):
        return False
    text = normalize_text(question)
    if any(term in text for term in ("descricao", "descricoes", "nome", "nomes")):
        return True
    if any(term in text for term in ("distribuicao", "distribuem", "ranking", "top", "mais", "maiores")):
        return True
    return any(f"por {trigger}" in text for trigger in link.triggers)
