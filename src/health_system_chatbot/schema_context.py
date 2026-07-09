from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .config import ChatbotConfig
from .models import RetrievedContext, Stage1Context, TableContext
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
    "internacoes": {
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
    "hospital": {"hospital", "hospitais", "cnes", "estabelecimento", "atendimento"},
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
    "socioeconomico": {"populacao", "habitante", "habitantes", "socioeconomico"},
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
    "internacoes": (
        "Tabela principal de internacoes hospitalares/AIH. Use esta tabela para "
        "perguntas de negocio sobre internacoes, idade do usuario, sexo, obito "
        "hospitalar, morte, permanencia, diagnostico principal, municipio de "
        "residencia e valores financeiros. Colunas importantes: SEXO, IDADE, "
        "MORTE, DT_INTER, DT_SAIDA, MUNIC_RES, VAL_TOT, DIAG_PRINC."
    ),
    "sexo": "Dimensao para interpretar internacoes.SEXO como masculino/feminino.",
    "municipios": "Dimensao territorial para municipio e UF.",
    "hospital": "Dimensao de estabelecimentos/CNES e municipio do hospital.",
    "cid": "Dimensao CID para diagnostico principal via internacoes.DIAG_PRINC.",
    "internacao_procedimento": "Tabela de ocorrencias de procedimentos por AIH.",
    "procedimentos": "Catalogo para interpretar internacoes.PROC_REA como procedimento principal.",
    "car_int": "Dimensao para interpretar internacoes.CAR_INT como carater de internacao.",
    "complexidade": "Dimensao para interpretar internacoes.COMPLEX como complexidade.",
    "marca_uti": "Dimensao para interpretar internacoes.MARCA_UTI como marca/uso de UTI.",
    "raca_cor": "Dimensao para interpretar internacoes.RACA_COR quando a relacao for aceitavel para a pergunta.",
    "instrucao": "Dimensao para interpretar internacoes.INSTRU como instrucao/escolaridade.",
    "vincprev": "Dimensao para interpretar internacoes.VINCPREV como vinculo previdenciario.",
    "nacionalidade": "Dimensao para interpretar internacoes.NACIONAL como nacionalidade.",
    "contraceptivos": "Dimensao para interpretar internacoes.CONTRACEP1 e CONTRACEP2.",
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
    if not _mentions_known_municipality(question, config):
        return
    if "internacoes" not in selected_table_names and "hospital" not in selected_table_names:
        _add_table_if_available(selected_table_names, selected_tables, ctx, "internacoes")

    _add_table_if_available(selected_table_names, selected_tables, ctx, "municipios")

    question_tokens = tokenize(question)
    if "internacoes" in selected_table_names and not question_tokens & RESIDENCE_TERMS:
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

    if "procedimento principal" in text or "procedimentos principais" in text:
        _add_table_if_available(selected_table_names, selected_tables, ctx, "internacoes")
        _add_table_if_available(selected_table_names, selected_tables, ctx, "procedimentos")

    if any(term in text for term in ("parto", "partos", "cesariano", "cesarianos", "cesariana")):
        _add_table_if_available(selected_table_names, selected_tables, ctx, "internacoes")
        _add_table_if_available(selected_table_names, selected_tables, ctx, "procedimentos")


def _build_columns(selected_tables: list[TableContext]) -> list[str]:
    columns: list[str] = []
    for table in selected_tables:
        columns.extend(f"{table.table_name}.{col}" for col in table.columns[:40])
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
) -> RetrievedContext:
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
