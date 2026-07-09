from __future__ import annotations

from typing import Literal

from pydantic_ai import RunContext

from ..agent_deps import ChatDeps
from ..catalogs.models import CatalogSearchResult


CidScope = Literal["diagnosis", "death_cause", "unknown"]
ProcedureScope = Literal["performed_procedure", "billing_procedure", "unknown"]


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
