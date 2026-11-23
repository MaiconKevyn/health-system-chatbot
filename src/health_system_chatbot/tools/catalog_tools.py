from __future__ import annotations

from typing import Literal

from pydantic_ai import RunContext

from ..agent_deps import ChatDeps
from ..catalogs.models import CatalogName, CatalogSearchResult
from ..errors import CatalogBudgetExceeded


CidScope = Literal["diagnosis", "death_cause", "unknown"]
ProcedureScope = Literal["performed_procedure", "billing_procedure", "unknown"]

GUARD_GUIDANCE = (
    "Nao repita esta busca. Use os candidatos de catalogo ja retornados nesta "
    "conversa e gere o SqlPlan agora."
)


def _guarded(
    deps: ChatDeps,
    *,
    tool: str,
    args: dict,
    catalog: CatalogName,
    query: str,
) -> CatalogSearchResult | None:
    """Apply the call guard without aborting the agent run.

    The retriever still raises and records the guard error for the trace, but a
    repeated or over-budget tool call is returned to the model as a warning
    instead of escaping ``agent.run_sync`` and failing the whole request.
    """
    try:
        deps.catalog_retriever.guard_tool_call(tool=tool, args=args)
    except CatalogBudgetExceeded as exc:
        return CatalogSearchResult(
            query=query,
            catalog=catalog,
            warnings=[str(exc), GUARD_GUIDANCE],
        )
    return None


def search_cid_catalog(
    deps: ChatDeps,
    *,
    query: str,
    scope: CidScope = "unknown",
    limit: int = 5,
) -> CatalogSearchResult:
    if deps.catalog_retriever is None:
        raise RuntimeError("Catalog retriever is not available.")
    args = {"query": query, "scope": scope, "limit": limit}
    blocked = _guarded(deps, tool="search_cid_catalog", args=args, catalog="cid", query=query)
    if blocked is not None:
        return blocked
    try:
        result = deps.catalog_retriever.search_cid(query, scope=scope, limit=limit)
        deps.catalog_retriever.record_tool_call(
            tool="search_cid_catalog",
            args=args,
            result=result,
        )
        return result
    except Exception as exc:
        deps.catalog_retriever.record_tool_call(
            tool="search_cid_catalog",
            args=args,
            error=str(exc),
        )
        raise


def search_procedure_catalog(
    deps: ChatDeps,
    *,
    query: str,
    scope: ProcedureScope = "unknown",
    limit: int = 5,
) -> CatalogSearchResult:
    if deps.catalog_retriever is None:
        raise RuntimeError("Catalog retriever is not available.")
    args = {"query": query, "scope": scope, "limit": limit}
    blocked = _guarded(
        deps, tool="search_procedure_catalog", args=args, catalog="procedimentos", query=query
    )
    if blocked is not None:
        return blocked
    try:
        result = deps.catalog_retriever.search_procedures(query, scope=scope, limit=limit)
        deps.catalog_retriever.record_tool_call(
            tool="search_procedure_catalog",
            args=args,
            result=result,
        )
        return result
    except Exception as exc:
        deps.catalog_retriever.record_tool_call(
            tool="search_procedure_catalog",
            args=args,
            error=str(exc),
        )
        raise


def search_dimension_values(
    deps: ChatDeps,
    *,
    table: str,
    query: str,
    limit: int = 5,
) -> CatalogSearchResult:
    if deps.catalog_retriever is None:
        raise RuntimeError("Catalog retriever is not available.")
    args = {"table": table, "query": query, "limit": limit}
    blocked = _guarded(
        deps,
        tool="search_dimension_values",
        args=args,
        catalog="municipios" if table == "municipios" else "dimension",
        query=query,
    )
    if blocked is not None:
        return blocked
    try:
        result = deps.catalog_retriever.search_dimension_values(
            table=table,
            query=query,
            limit=limit,
        )
        deps.catalog_retriever.record_tool_call(
            tool="search_dimension_values",
            args=args,
            result=result,
        )
        return result
    except Exception as exc:
        deps.catalog_retriever.record_tool_call(
            tool="search_dimension_values",
            args=args,
            error=str(exc),
        )
        raise


def register_catalog_tools(agent) -> None:
    @agent.tool
    def search_cid_catalog_tool(
        ctx: RunContext[ChatDeps],
        query: str,
        scope: CidScope = "unknown",
        limit: int = 5,
    ) -> CatalogSearchResult:
        """Search the local CID catalog for disease, diagnosis or death-cause concepts."""

        return search_cid_catalog(ctx.deps, query=query, scope=scope, limit=limit)

    @agent.tool
    def search_procedure_catalog_tool(
        ctx: RunContext[ChatDeps],
        query: str,
        scope: ProcedureScope = "unknown",
        limit: int = 5,
    ) -> CatalogSearchResult:
        """Search the local procedures catalog for performed or billed procedure concepts."""

        return search_procedure_catalog(ctx.deps, query=query, scope=scope, limit=limit)

    @agent.tool
    def search_dimension_values_tool(
        ctx: RunContext[ChatDeps],
        table: str,
        query: str,
        limit: int = 5,
    ) -> CatalogSearchResult:
        """Search known local dimension tables for textual business values."""

        return search_dimension_values(ctx.deps, table=table, query=query, limit=limit)
