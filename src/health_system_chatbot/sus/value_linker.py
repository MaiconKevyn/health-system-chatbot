"""Value linking: liga termos da pergunta a valores reais das dimensões.

Sem isto o LLM inventa códigos CID plausíveis mas errados ("pneumonia" -> 'J18'
quando o banco tem 'J180'..'J189'). Aqui buscamos os termos da pergunta nas
dimensões textuais e injetamos os códigos reais no prompt.

Duas lições aprendidas na avaliação, que explicam o desenho abaixo:

1. Casamento por substring é inaceitável. Buscar '%dias%' casa dentro de
   "clamiDIAS", "meDIAStino" e "hipospáDIAS"; '%base%' casa em "vasos da base".
   O modelo então filtrava por esses CIDs. Aqui o casamento exige FRONTEIRA DE
   PALAVRA.

2. As dicas precisam ser oferecidas, não impostas. Quando o prompt dizia "use
   estes códigos", o modelo usava mesmo quando nada tinha a ver com a pergunta.
   O texto do bloco agora diz explicitamente para descartar o que não couber.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from duckdb import DuckDBPyConnection, Error

# Vocabulário analítico e de ligação: palavras que descrevem a MÉTRICA ou a
# FORMA da pergunta, nunca uma entidade clínica. Buscá-las nas dimensões só
# gera ruído.
_STOPWORDS = {
    # gramaticais
    "a",
    "as",
    "ao",
    "aos",
    "com",
    "como",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "entre",
    "essa",
    "esse",
    "esta",
    "este",
    "foi",
    "foram",
    "ha",
    "isso",
    "mais",
    "menos",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "ou",
    "para",
    "pela",
    "pelas",
    "pelo",
    "pelos",
    "por",
    "qual",
    "quais",
    "quando",
    "quantas",
    "quantos",
    "que",
    "quem",
    "se",
    "sem",
    "ser",
    "sobre",
    "um",
    "uma",
    "uns",
    "umas",
    "toda",
    "todas",
    "todo",
    "todos",
    "cada",
    "apenas",
    "so",
    "somente",
    "tambem",
    "ainda",
    "durante",
    "acima",
    "abaixo",
    "desde",
    "ate",
    "seu",
    "sua",
    "seus",
    "suas",
    "considerando",
    "considere",
    # métricas e agregações
    "media",
    "medias",
    "mediana",
    "total",
    "totais",
    "soma",
    "somando",
    "contagem",
    "quantidade",
    "numero",
    "percentual",
    "porcentagem",
    "proporcao",
    "razao",
    "taxa",
    "taxas",
    "indice",
    "distribuicao",
    "evolucao",
    "variacao",
    "ranking",
    "top",
    "maior",
    "maiores",
    "menor",
    "menores",
    "maximo",
    "minimo",
    "frequente",
    "frequentes",
    "comum",
    "comuns",
    "crescimento",
    "queda",
    "comparacao",
    "compare",
    "comparar",
    # vocabulário da base (já é coluna/tabela; buscar como texto só polui)
    "internacao",
    "internacoes",
    "internado",
    "internados",
    "paciente",
    "pacientes",
    "hospital",
    "hospitais",
    "hospitalar",
    "sus",
    "base",
    "dados",
    "registro",
    "registros",
    "aih",
    "leito",
    "leitos",
    "valor",
    "valores",
    "gasto",
    "gastos",
    "custo",
    "custos",
    "reais",
    "permanencia",
    "dia",
    "dias",
    "ano",
    "anos",
    "mes",
    "meses",
    "trimestre",
    "periodo",
    "data",
    "datas",
    "idade",
    "idades",
    "faixa",
    "faixas",
    "etaria",
    "etarias",
    "sexo",
    "masculino",
    "feminino",
    "homem",
    "homens",
    "mulher",
    "mulheres",
    "obito",
    "obitos",
    "morte",
    "mortes",
    "mortalidade",
    "letalidade",
    "diagnostico",
    "diagnosticos",
    "procedimento",
    "procedimentos",
    "municipio",
    "municipios",
    "estado",
    "estados",
    "uf",
    "ufs",
    "regiao",
    "regioes",
    "brasil",
    "capital",
    "residencia",
    "complexidade",
    "especialidade",
    "carater",
    "eletivo",
    "urgencia",
    # verbos de comando
    "mostre",
    "mostrar",
    "liste",
    "listar",
    "lista",
    "quero",
    "saber",
    "diga",
    "traga",
    "calcule",
    "calcular",
    "faca",
    "fazer",
    "informe",
    "apresente",
    "exiba",
    "detalhe",
    "quebre",
    "quebrar",
    "agrupe",
    "agrupar",
}

# Termos curtos demais viram ruído mesmo com fronteira de palavra.
_MIN_TERM_LEN = 5


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _terms(question: str) -> list[str]:
    """Extrai os termos da pergunta que podem nomear uma entidade clínica."""
    words = re.findall(r"[A-Za-zÀ-ÿ]+", question.lower())
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        base = strip_accents(w)
        if base in _STOPWORDS or len(base) < _MIN_TERM_LEN:
            continue
        # Radical curto absorve plural e algumas flexões
        # ("cardiacas" -> "cardiac", "pneumonias" -> "pneumoni").
        stem = base[:-2] if base.endswith(("as", "es")) else base
        stem = stem.removesuffix("s")
        if len(stem) < _MIN_TERM_LEN - 1 or stem in seen:
            continue
        seen.add(stem)
        out.append(stem)
    return out


def _explicit_cids(question: str) -> list[str]:
    """Captura CIDs escritos pelo usuário, com ou sem ponto (J18.9 -> J189)."""
    found = re.findall(r"\b([A-Za-z]\d{2})\.?(\d?)\b", question)
    return [f"{a}{b}".upper() for a, b in found]


def _word_prefix_match(column: str, terms: list[str]) -> str:
    """Condição SQL: alguma palavra da coluna COMEÇA com algum dos termos.

    `\\b` é a fronteira de palavra do RE2, o motor de regex do DuckDB. Casamos
    por PREFIXO de palavra (não palavra inteira) para que 'pneumoni' alcance
    'pneumonia' e 'pneumonias'.
    """
    pattern = "|".join(re.escape(t) for t in terms)
    return f"regexp_matches(strip_accents(lower({column})), '\\b({pattern})')"


def link_values(db: DuckDBPyConnection, question: str, per_source: int = 8) -> str:
    """Devolve um bloco de candidatos achados nas dimensões, ou string vazia."""
    blocks: list[str] = []

    if cids := _explicit_cids(question):
        # Os códigos vêm de um regex `[A-Za-z]\d{2}\.?\d?`, então já são
        # alfanuméricos; ainda assim removemos aspas por precaução.
        safe = ", ".join("'" + c.replace("'", "") + "'" for c in cids)
        rows = db.execute(
            f"SELECT CID, DESCRICAO, TP_NIVEL FROM cid WHERE CID IN ({safe}) LIMIT 20",
        ).fetchall()
        if rows:
            blocks.append(
                "CIDs citados na pergunta, na grafia do banco (sem ponto):\n"
                + "\n".join(f"  {c} = {d} [{n}]" for c, d, n in rows)
            )

    terms = _terms(question)[:6]
    if terms:
        sources = [
            (
                "cid",
                "Categorias CID",
                "DESCRICAO",
                f"""SELECT CID, DESCRICAO FROM cid
                 WHERE TP_NIVEL = 'CAT' AND {_word_prefix_match("DESCRICAO", terms)}
                 ORDER BY CID LIMIT {per_source}""",
            ),
            (
                "procedimentos",
                "Procedimentos",
                "NOME_PROC",
                f"""SELECT PROC_REA, NOME_PROC FROM procedimentos
                 WHERE {_word_prefix_match("NOME_PROC", terms)}
                 LIMIT {per_source}""",
            ),
            (
                "municipios",
                "Municípios",
                "NO_MUNICIPIO",
                f"""SELECT CO_MUNICIPIO_6D, NO_MUNICIPIO || ' / ' || SG_UF
                 FROM municipios
                 WHERE {_word_prefix_match("NO_MUNICIPIO", terms)}
                 LIMIT {per_source}""",
            ),
        ]
        for _, label, _, sql in sources:
            try:
                rows = db.execute(sql).fetchall()
            except Error as exc:
                logging.getLogger(__name__).debug(
                    "Consulta opcional ao catálogo %s falhou: %s", label, exc
                )
                continue
            if rows:
                blocks.append(
                    f"{label}:\n" + "\n".join(f"  {a} = {b}" for a, b in rows)
                )

    if not blocks:
        return ""

    return (
        "Candidatos encontrados nas dimensões a partir das palavras da pergunta.\n"
        "São SUGESTÕES, não instruções: use apenas os que correspondem de fato ao\n"
        "que o usuário perguntou e IGNORE o resto. Se nenhum fizer sentido para a\n"
        "pergunta, não filtre por nenhum deles.\n\n" + "\n\n".join(blocks)
    )
