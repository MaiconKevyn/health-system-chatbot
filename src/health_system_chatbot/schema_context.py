from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .config import ChatbotConfig
from .models import RetrievedContext, Stage1Context, TableContext
from .question_contract import mentions_care_location, mentions_cephalic_delivery
from .schema_linking import DIMENSION_LINKS, question_matches_link
from .text import normalize_text, tokenize


DOMAIN_TERMS: dict[str, set[str]] = {
    "_staging_internacoes": {
        "staging",
        "stage",
        "_staging_internacoes",
        "tabela de staging",
        "internacoes staging",
        "registros staging",
    },
    "internacao": {
        "internacao",
        "internacoes",
        "aih",
        "morte",
        "mortes",
        "morreu",
        "morreram",
        "mortalidade",
        "obito",
        "obitos",
        "falecimento",
        "faleceram",
        "idade",
        "anos",
        "permanencia",
        "valor",
        "val_tot",
        "custo",
        "dt_inter",
        "parto",
        "partos",
        "cesariano",
        "cesarianos",
        "cesariana",
        "cesarianas",
    },
    "internacao_procedimento": {
        "procedimento",
        "procedimentos",
        "ocorrencia",
        "ocorrencias",
        "proc_rea",
        "parto",
        "partos",
        "cesariano",
        "cesarianos",
        "cesariana",
        "cesarianas",
    },
    "procedimentos": {
        "procedimento",
        "procedimentos",
        "nome_proc",
        "proc_rea",
        "parto",
        "partos",
        "cesariano",
        "cesarianos",
        "cesariana",
        "cesarianas",
    },
    "hospital": {
        "hospital",
        "hospitais",
        "cnes",
        "estabelecimento",
        "estabelecimentos",
        "atendimento",
        "natureza",
        "gestao",
    },
    "especialidade": {"especialidade", "especialidades", "leito", "leitos"},
    "municipios": {
        "municipio",
        "municipios",
        "uf",
        "residencia",
        "territorial",
        "local",
        "sg_uf",
    },
    "sexo": {
        "sexo",
        "homem",
        "homens",
        "masculino",
        "masculina",
        "mulher",
        "mulheres",
        "feminino",
        "feminina",
    },
    "cid": {
        "cid",
        "diagnostico",
        "diagnosticos",
        "capitulo",
        "causa",
        "causas",
        "doenca",
        "doencas",
        "infecc",
        "infeccao",
        "infeccoes",
        "infecciosa",
        "infecciosas",
        "neoplasia",
        "neoplasias",
        "cancer",
    },
    "car_int": {"carater", "carater de internacao", "urgencia", "eletivo"},
    "complexidade": {"complexidade", "complex"},
    "marca_uti": {"marca uti", "uti"},
    "raca_cor": {"raca", "cor", "raca cor"},
    "instrucao": {"instrucao", "escolaridade"},
    "vincprev": {"vinculo", "previdenciario", "vincprev"},
    "nacionalidade": {"nacionalidade", "nacionalidades"},
    "contraceptivos": {"contraceptivo", "contraceptivo 1", "contraceptivo 2"},
    "socioeconomico": {
        "populacao",
        "habitante",
        "habitantes",
        "socioeconomico",
        "pib",
        "medicos",
        "enfermeiros",
        "nascidos",
        "transito",
    },
    "tempo": {"ano", "mes", "data", "periodo", "temporal"},
}

PLACE_PHRASE_RE = re.compile(
    r"\b(?:em|de|do|da|no|na)\s+"
    r"([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç-]*"
    r"(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç-]*){0,3})"
)

RESIDENCE_TERMS = {
    "residencia",
    "residente",
    "residentes",
    "morador",
    "moradores",
}

BUSINESS_TABLE_NOTES: dict[str, str] = {
    "_staging_internacoes": (
        "Tabela de staging de internacoes. Use somente quando a pergunta mencionar "
        "staging ou a tabela _staging_internacoes; nao substitua por internacoes."
    ),
    "internacao": (
        "Tabela principal de internacoes hospitalares/AIH (uma linha por N_AIH, "
        "DT_INTER de 2008-01-01 a 2025-12-31). Use esta tabela para perguntas de "
        "negocio sobre internacoes, idade do usuario, sexo, obito hospitalar, "
        "morte, permanencia, diagnostico principal, municipio de residencia, "
        "hospital (CNES) e valores financeiros. Colunas importantes: SEXO, IDADE, "
        "MORTE, DT_INTER, DT_SAIDA, MUNIC_RES, CNES, VAL_TOT, DIAG_PRINC. IDADE ja "
        "esta em anos completos; COD_IDADE so indica a unidade original. Nao ha "
        "coluna de procedimento: use internacao_procedimento."
    ),
    "sexo": "Dimensao para interpretar internacao.SEXO como masculino/feminino.",
    "municipios": (
        "Dimensao territorial para municipio, UF e regiao de saude. Chave "
        "CO_MUNICIPIO_6D; serve tanto internacao.MUNIC_RES (residencia) quanto "
        "hospital.MUNIC_MOV (municipio do hospital)."
    ),
    "hospital": (
        "Cadastro de estabelecimentos por CNES (internacao.CNES -> hospital.CNES "
        "cobre 100% das internacoes). Nome em NO_HOSPITAL; municipio do hospital em "
        "MUNIC_MOV (join com municipios.CO_MUNICIPIO_6D)."
    ),
    "cid": (
        "Dimensao CID para diagnostico principal via internacao.DIAG_PRINC. Alguns "
        "codigos raros (ex.: U04, U09, U10, N182-N185) existem apenas em cid_manuais."
    ),
    "cid_manuais": (
        "Complemento manual de cid com as mesmas colunas e sem sobreposicao de "
        "codigos. Use cid UNION ALL cid_manuais quando precisar descrever todos os "
        "codigos de DIAG_PRINC."
    ),
    "internacao_procedimento": (
        "Procedimento realizado (PROC_REA) por AIH, ligado a internacao por N_AIH. "
        "AIHs de longa permanencia repetem linhas: COUNT(*) conta ocorrencias; use "
        "COUNT(DISTINCT N_AIH) ou EXISTS para contar internacoes."
    ),
    "procedimentos": (
        "Catalogo para interpretar internacao_procedimento.PROC_REA (NOME_PROC). "
        "Alguns codigos existem apenas em procedimentos_manuais."
    ),
    "procedimentos_manuais": (
        "Complemento manual de procedimentos com as mesmas colunas e sem "
        "sobreposicao de codigos."
    ),
    "especialidade": "Dimensao para interpretar internacao.ESPEC como especialidade do leito.",
    "socioeconomico": (
        "Indicadores municipais anuais (CO_MUNICIPIO_6D, NU_ANO). Cobre 2008-2024 "
        "sem os anos 2010, 2022 e 2023; declare o ano usado como denominador."
    ),
    "car_int": "Dimensao para interpretar internacao.CAR_INT como carater de internacao.",
    "complexidade": "Dimensao para interpretar internacao.COMPLEX como complexidade.",
    "marca_uti": "Dimensao para interpretar internacao.MARCA_UTI como marca/uso de UTI.",
    "raca_cor": "Dimensao para interpretar internacao.RACA_COR quando a relacao for aceitavel para a pergunta.",
    "instrucao": "Dimensao para interpretar internacao.INSTRU como instrucao/escolaridade.",
    "vincprev": "Dimensao para interpretar internacao.VINCPREV como vinculo previdenciario.",
    "nacionalidade": "Dimensao para interpretar internacao.NACIONAL como nacionalidade.",
    "contraceptivos": (
        "Dimensao para interpretar internacao.CONTRACEP1 e CONTRACEP2. O codigo 0 "
        "(nao informado) nao existe na dimensao: use LEFT JOIN para distribuicoes."
    ),
    "tempo": (
        "Calendario (data, ano, mes, trimestre, dia_semana 1=segunda..7=domingo) "
        "que cobre apenas 2008-01-01 a 2024-12-31. Join com DT_INTER descarta as "
        "internacoes de 2025; prefira isodow(DT_INTER), month(DT_INTER) etc."
    ),
}


def is_runtime_business_table(table: TableContext) -> bool:
    if table.schema_name != "main":
        return False
    blocked_prefixes = (
        "stg_",
        "source_",
        "relationships_",
        "not_null_",
        "accepted_values_",
        "dbt_",
    )
    return not table.table_name.startswith(blocked_prefixes)


def table_document(table: TableContext) -> str:
    cols = ", ".join(table.columns[:80]) if table.columns else "columns not profiled"
    notes = " | ".join(table.notes[:10])
    business_note = BUSINESS_TABLE_NOTES.get(table.table_name, "")
    return (
        f"table={table.table_name}\n"
        f"schema={table.schema_name}\n"
        f"column_count={table.column_count}\n"
        f"business_note={business_note}\n"
        f"columns={cols}\n"
        f"notes={notes}"
    )


def _score_table(question_tokens: set[str], question: str, table: TableContext) -> float:
    normalized_question = normalize_text(question)
    if table.table_name == "_staging_internacoes" and not (
        "staging" in normalized_question or "_staging_internacoes" in normalized_question
    ):
        return 0.0
    haystack = " ".join(
        [
            table.table_name,
            " ".join(table.columns),
            " ".join(table.notes),
            " ".join(DOMAIN_TERMS.get(table.table_name, set())),
        ]
    )
    hay_tokens = tokenize(haystack)
    overlap = len(question_tokens & hay_tokens)
    name_bonus = 3.0 if table.table_name in normalized_question else 0.0
    domain_bonus = len(question_tokens & DOMAIN_TERMS.get(table.table_name, set())) * 1.5
    return overlap + name_bonus + domain_bonus


def _selected_policies(ctx: Stage1Context, selected_table_names: set[str]):
    policies = []
    for policy in ctx.join_policies:
        left_table = policy.left.split(".")[0]
        right_table = policy.right.split(".")[0]
        if left_table in selected_table_names or right_table in selected_table_names:
            policies.append(policy)
    return policies


@lru_cache(maxsize=4)
def _municipality_names_from_db(db_path: str) -> frozenset[str]:
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT NO_MUNICIPIO FROM municipios WHERE NO_MUNICIPIO IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    return frozenset(normalize_text(row[0]) for row in rows if row and row[0])


def _has_place_like_phrase(question: str) -> bool:
    for match in PLACE_PHRASE_RE.finditer(question):
        phrase = match.group(1)
        if any(ch.islower() for ch in phrase):
            return True
    return False


def _mentions_known_municipality(question: str, config: ChatbotConfig | None) -> bool:
    if _has_place_like_phrase(question):
        return True
    if config is None or not config.db_path.exists():
        return False
    normalized = f" {normalize_text(question)} "
    try:
        names = _municipality_names_from_db(str(config.db_path))
    except Exception:
        return False
    return any(f" {name} " in normalized for name in names if name)


def _add_table_if_available(
    selected_table_names: set[str],
    selected_tables: list[TableContext],
    ctx: Stage1Context,
    table_name: str,
) -> None:
    if table_name in selected_table_names or table_name not in ctx.tables:
        return
    table = ctx.tables[table_name]
    if not is_runtime_business_table(table):
        return
    selected_table_names.add(table_name)
    selected_tables.append(table)


def _ensure_geography_tables(
    question: str,
    ctx: Stage1Context,
    selected_table_names: set[str],
    selected_tables: list[TableContext],
    config: ChatbotConfig | None,
) -> None:
    care_location = mentions_care_location(question)
    if not care_location and not _mentions_known_municipality(question, config):
        return
    if "internacao" not in selected_table_names and "hospital" not in selected_table_names:
        _add_table_if_available(selected_table_names, selected_tables, ctx, "internacao")

    _add_table_if_available(selected_table_names, selected_tables, ctx, "municipios")

    question_tokens = tokenize(question)
    if "internacao" in selected_table_names and (care_location or not question_tokens & RESIDENCE_TERMS):
        _add_table_if_available(selected_table_names, selected_tables, ctx, "hospital")


def _ensure_schema_link_tables(
    question: str,
    ctx: Stage1Context,
    selected_table_names: set[str],
    selected_tables: list[TableContext],
) -> None:
    text = normalize_text(question)
    if "staging" in text or "_staging_internacoes" in text:
        _add_table_if_available(selected_table_names, selected_tables, ctx, "_staging_internacoes")
        return

    for link in DIMENSION_LINKS:
        if not question_matches_link(question, link):
            continue
        _add_table_if_available(selected_table_names, selected_tables, ctx, link.fact_table)
        _add_table_if_available(selected_table_names, selected_tables, ctx, link.dimension_table)

    if mentions_cephalic_delivery(text):
        for table_name in ("internacao", "cid"):
            _add_table_if_available(selected_table_names, selected_tables, ctx, table_name)
    elif (
        "procedimento principal" in text
        or "procedimentos principais" in text
        or any(term in text for term in ("parto", "partos", "cesariano", "cesarianos", "cesariana"))
    ):
        for table_name in ("internacao", "internacao_procedimento", "procedimentos"):
            _add_table_if_available(selected_table_names, selected_tables, ctx, table_name)


def _build_columns(selected_tables: list[TableContext]) -> list[str]:
    columns: list[str] = []
    for table in selected_tables:
        # The fact table has 47 columns; a 40-column cap silently dropped
        # MUNIC_RES/CBOR/CONTRACEP* from the prompt's column list.
        columns.extend(f"{table.table_name}.{col}" for col in table.columns[:80])
    return columns


def _finalize_retrieved_context(
    *,
    question: str,
    ctx: Stage1Context,
    selected_tables: list[TableContext],
    selected_table_names: set[str],
    config: ChatbotConfig | None,
    table_context: list[str] | None = None,
) -> tuple[list[str], list[str], list[str], list]:
    _ensure_geography_tables(question, ctx, selected_table_names, selected_tables, config)
    _ensure_schema_link_tables(question, ctx, selected_table_names, selected_tables)

    documented = set()
    final_table_context: list[str] = []
    for document in table_context or []:
        match = re.search(r"^table=([^\n]+)", document)
        if match:
            documented.add(match.group(1))
        final_table_context.append(document)
    for table in selected_tables:
        if table.table_name not in documented:
            final_table_context.append(table_document(table))
            documented.add(table.table_name)

    return (
        sorted(selected_table_names),
        _build_columns(selected_tables),
        final_table_context,
        _selected_policies(ctx, selected_table_names),
    )


def _should_use_vector(config: ChatbotConfig) -> bool:
    if config.schema_retrieval_mode == "keyword":
        return False
    if config.schema_retrieval_mode == "llamaindex_vector":
        return True
    return config.agent_framework == "llamaindex"


def retrieve_context(
    question: str,
    ctx: Stage1Context,
    *,
    top_k_tables: int = 6,
    config: ChatbotConfig | None = None,
    use_vector: bool = True,
    include_query_examples: bool = True,
) -> RetrievedContext:
    effective_query_examples = include_query_examples and (
        config is None or config.query_examples_enabled
    )
    if config is not None and use_vector and config.has_openai_key and _should_use_vector(config):
        vector_context = retrieve_context_with_index(
            question,
            ctx,
            config,
            top_k_tables=top_k_tables,
        )
        if vector_context.table_context:
            if not config.context_enrichment_enabled:
                return vector_context
            from .context_retrieval import enrich_retrieved_context

            return enrich_retrieved_context(
                question=question,
                ctx=ctx,
                retrieved=vector_context,
                config=config,
                include_query_examples=effective_query_examples,
            )

    question_tokens = tokenize(question)
    ranked_tables = sorted(
        [table for table in ctx.tables.values() if is_runtime_business_table(table)],
        key=lambda table: _score_table(question_tokens, question, table),
        reverse=True,
    )
    selected_tables = [
        table for table in ranked_tables if _score_table(question_tokens, question, table) > 0
    ][:top_k_tables]

    selected_table_names = {table.table_name for table in selected_tables}
    tables, columns, table_context, selected_policies = _finalize_retrieved_context(
        question=question,
        ctx=ctx,
        selected_tables=selected_tables,
        selected_table_names=selected_table_names,
        config=config,
    )

    caveats = []
    for line in ctx.readiness_notes.splitlines():
        stripped = line.strip("- ").strip()
        if stripped and any(term in normalize_text(stripped) for term in question_tokens):
            caveats.append(stripped)
    if not caveats:
        caveats = [
            "Diferenciar municipio de residencia de municipio do hospital quando houver geografia.",
            "Declarar a base da metrica financeira quando houver valor/custo.",
            "Avisar quando procedimentos mudarem a unidade de analise para ocorrencias.",
        ]

    retrieved = RetrievedContext(
        tables=tables,
        columns=columns,
        table_context=table_context,
        join_policies=selected_policies,
        data_quality_caveats=caveats[:8],
        retrieval_mode="schema_keyword",
    )
    if config is not None and not config.context_enrichment_enabled:
        return retrieved
    from .context_retrieval import enrich_retrieved_context

    return enrich_retrieved_context(
        question=question,
        ctx=ctx,
        retrieved=retrieved,
        config=config,
        include_query_examples=effective_query_examples,
    )


def build_schema_index(ctx: Stage1Context, config: ChatbotConfig) -> Path:
    if not config.has_openai_key:
        raise RuntimeError("OPENAI_API_KEY is required to build the LlamaIndex schema index")

    from llama_index.core import Document, Settings, VectorStoreIndex
    from llama_index.embeddings.openai import OpenAIEmbedding

    Settings.embed_model = OpenAIEmbedding(model=config.embed_model, api_key=config.openai_api_key)
    docs = [
        Document(text=table_document(table), metadata={"table_name": table.table_name})
        for table in ctx.tables.values()
        if is_runtime_business_table(table)
    ]
    index = VectorStoreIndex.from_documents(docs)
    persist_dir = config.index_dir or (Path(ctx.project_root) / ".chatbot_index")
    persist_dir.mkdir(parents=True, exist_ok=True)
    index.storage_context.persist(persist_dir=str(persist_dir))
    return persist_dir


def retrieve_context_with_index(
    question: str,
    ctx: Stage1Context,
    config: ChatbotConfig,
    *,
    top_k_tables: int = 6,
) -> RetrievedContext:
    from llama_index.core import Settings, StorageContext, load_index_from_storage
    from llama_index.embeddings.openai import OpenAIEmbedding

    persist_dir = config.index_dir or (Path(ctx.project_root) / ".chatbot_index")
    if not (persist_dir / "index_store.json").exists():
        build_schema_index(ctx, config)

    Settings.embed_model = OpenAIEmbedding(model=config.embed_model, api_key=config.openai_api_key)
    storage_context = StorageContext.from_defaults(persist_dir=str(persist_dir))
    index = load_index_from_storage(storage_context)
    retriever = index.as_retriever(similarity_top_k=top_k_tables)
    nodes = retriever.retrieve(question)

    selected_table_names: set[str] = set()
    table_context: list[str] = []
    for node in nodes:
        metadata = getattr(node.node, "metadata", {}) or {}
        table_name = metadata.get("table_name")
        if table_name and table_name in ctx.tables and is_runtime_business_table(ctx.tables[table_name]):
            selected_table_names.add(table_name)
            table_context.append(node.node.get_content())

    selected_tables = [ctx.tables[name] for name in selected_table_names if name in ctx.tables]
    tables, columns, table_context, selected_policies = _finalize_retrieved_context(
        question=question,
        ctx=ctx,
        selected_tables=selected_tables,
        selected_table_names=selected_table_names,
        config=config,
        table_context=table_context,
    )

    question_tokens = tokenize(question)
    caveats = []
    for line in ctx.readiness_notes.splitlines():
        stripped = line.strip("- ").strip()
        if stripped and any(term in normalize_text(stripped) for term in question_tokens):
            caveats.append(stripped)
    if not caveats:
        caveats = [
            "Diferenciar municipio de residencia de municipio do hospital quando houver geografia.",
            "Declarar a base da metrica financeira quando houver valor/custo.",
            "Avisar quando procedimentos mudarem a unidade de analise para ocorrencias.",
        ]

    return RetrievedContext(
        tables=tables,
        columns=columns,
        table_context=table_context,
        join_policies=selected_policies,
        data_quality_caveats=caveats[:8],
        retrieval_mode="llamaindex_vector",
    )
