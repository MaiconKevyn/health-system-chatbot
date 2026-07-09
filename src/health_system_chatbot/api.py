from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import duckdb
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .artifacts import load_stage1_context
from .config import ChatbotConfig, load_config
from .duckdb_executor import execute_validated_sql
from .models import ChatbotAnswer, Stage1Context, TableContext
from .sql_validator import validate_sql
from .workflow import run_chat


STATIC_DIR = Path(__file__).with_name("static")


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    show_sql: bool = False
    allow_llm: bool = True
    show_debug: bool = False

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("question must not be blank")
        return question


class SchemaResponse(BaseModel):
    schema_text: str = Field(serialization_alias="schema")
    tables: list[str] = Field(default_factory=list)
    selected_table: str | None = None
    timestamp: str


class ModelsResponse(BaseModel):
    available_models: dict[str, list[str]]
    current_model: dict[str, Any]
    timestamp: str


class DatabaseTableSummary(BaseModel):
    table_schema: str = "main"
    table_name: str
    table_type: str = "BASE TABLE"
    row_count: int | None = None
    classification: str | None = None


class DatabaseOverviewResponse(BaseModel):
    database_url: str
    tables: list[DatabaseTableSummary]
    generated_docs: list[str] = Field(default_factory=list)
    timestamp: str


class DatabaseColumn(BaseModel):
    ordinal_position: int
    column_name: str
    data_type: str
    is_nullable: str | None = None


class DatabaseTableDetailResponse(BaseModel):
    table_schema: str
    table_name: str
    columns: list[DatabaseColumn]
    sample_columns: list[str]
    sample_rows: list[dict[str, Any]]
    sample_limit: int
    timestamp: str


class DatabaseQueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=10000)
    limit: int = Field(default=100, ge=1, le=500)


class DatabaseQueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    limit: int
    sql: str
    execution_time: float
    timestamp: str
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class ChatService:
    def __init__(self, *, config: ChatbotConfig, stage1_context: Stage1Context) -> None:
        self.config = config
        self.stage1_context = stage1_context

    @classmethod
    def from_environment(cls) -> "ChatService":
        config = load_config()
        return cls(
            config=config,
            stage1_context=load_stage1_context(config.project_root, db_path=config.db_path),
        )

    def ask(
        self,
        question: str,
        *,
        show_sql: bool,
        allow_llm: bool,
        show_debug: bool,
    ) -> ChatbotAnswer:
        return run_chat(
            question,
            config=self.config,
            stage1_context=self.stage1_context,
            show_sql=show_sql,
            allow_llm=allow_llm,
            show_debug=show_debug,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frontend_dist_dir(project_root: Path) -> Path:
    return project_root / "frontend" / "dist"


def _project_root_from_service(chat_service: object | None) -> Path:
    config = getattr(chat_service, "config", None)
    if config is not None and getattr(config, "project_root", None) is not None:
        return config.project_root
    return load_config().project_root


def _table_names(stage1_context: Stage1Context) -> list[str]:
    return sorted(stage1_context.tables)


def _find_table_context(stage1_context: Stage1Context, table_name: str) -> TableContext:
    if table_name in stage1_context.tables:
        return stage1_context.tables[table_name]
    lowered = table_name.lower()
    for candidate, table_context in stage1_context.tables.items():
        if candidate.lower() == lowered:
            return table_context
    raise HTTPException(status_code=404, detail=f"Unknown table: {table_name}")


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _schema_markdown(stage1_context: Stage1Context, table_name: str | None = None) -> str:
    selected_tables = (
        [_find_table_context(stage1_context, table_name)]
        if table_name
        else [stage1_context.tables[name] for name in _table_names(stage1_context)]
    )
    sections = ["# Esquema do banco"]
    for table in selected_tables:
        sections.append("")
        sections.append(f"## {table.table_name}")
        if table.estimated_size is not None:
            sections.append(f"Linhas estimadas: {table.estimated_size}")
        if table.notes:
            sections.append("Notas:")
            sections.extend(f"- {note}" for note in table.notes[:8])
        columns = table.columns or list(table.column_types)
        if columns:
            sections.append("Colunas:")
            for column in columns:
                data_type = table.column_types.get(column, "unknown")
                sections.append(f"- `{column}`: {data_type}")
    return "\n".join(sections)


def _table_columns(table_context: TableContext) -> list[DatabaseColumn]:
    columns = table_context.columns or list(table_context.column_types)
    return [
        DatabaseColumn(
            ordinal_position=index,
            column_name=column,
            data_type=table_context.column_types.get(column, "unknown"),
            is_nullable=None,
        )
        for index, column in enumerate(columns, start=1)
    ]


def _sample_table_rows(
    *,
    config: ChatbotConfig,
    stage1_context: Stage1Context,
    table_name: str,
    limit: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    table_context = _find_table_context(stage1_context, table_name)
    safe_limit = max(1, min(limit, 500))
    sql = f"SELECT * FROM {_quote_identifier(table_context.table_name)} LIMIT {safe_limit}"
    con = duckdb.connect(str(config.db_path), read_only=True)
    try:
        cursor = con.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
    finally:
        con.close()
    return columns, [
        {columns[index]: value for index, value in enumerate(row)}
        for row in rows
    ]


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService.from_environment()


def create_app(*, chat_service: ChatService | None = None) -> FastAPI:
    project_root = _project_root_from_service(chat_service)
    frontend_dist = _frontend_dist_dir(project_root)
    frontend_assets = frontend_dist / "assets"

    app = FastAPI(
        title="Health System Chatbot",
        version="0.1.0",
    )

    def resolve_chat_service() -> ChatService:
        return chat_service or get_chat_service()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    if frontend_assets.exists():
        app.mount("/assets", StaticFiles(directory=frontend_assets), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        frontend_index = frontend_dist / "index.html"
        if frontend_index.exists():
            return FileResponse(frontend_index)
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "health-system-chatbot",
            "fastapi": True,
        }

    @app.get("/api/health")
    def api_health() -> dict[str, object]:
        return {
            "status": "healthy",
            "service": "health-system-chatbot",
            "timestamp": _utc_now(),
        }

    @app.get("/api/agent-health")
    def agent_health(service: ChatService = Depends(resolve_chat_service)) -> dict[str, object]:
        return {
            "agent_status": "online",
            "agent_health": {
                "status": "ok",
                "config": service.config.safe_summary(),
            },
            "timestamp": _utc_now(),
        }

    @app.get("/api/schema", response_model=SchemaResponse)
    def schema(
        table: str | None = None,
        service: ChatService = Depends(resolve_chat_service),
    ) -> SchemaResponse:
        selected_table = table.strip() if table else None
        return SchemaResponse(
            schema_text=_schema_markdown(service.stage1_context, selected_table),
            tables=_table_names(service.stage1_context),
            selected_table=selected_table,
            timestamp=_utc_now(),
        )

    @app.get("/api/models", response_model=ModelsResponse)
    def models(service: ChatService = Depends(resolve_chat_service)) -> ModelsResponse:
        return ModelsResponse(
            available_models={"openai": [service.config.llm_model]},
            current_model={
                "provider": service.config.llm_provider,
                "model_name": service.config.llm_model,
                "agent_framework": service.config.agent_framework,
            },
            timestamp=_utc_now(),
        )

    @app.get("/api/database/overview", response_model=DatabaseOverviewResponse)
    def database_overview(
        service: ChatService = Depends(resolve_chat_service),
    ) -> DatabaseOverviewResponse:
        tables = [
            DatabaseTableSummary(
                table_schema=table.schema_name,
                table_name=table.table_name,
                row_count=table.estimated_size,
                classification="runtime_catalog",
            )
            for table in sorted(
                service.stage1_context.tables.values(),
                key=lambda item: item.table_name,
            )
        ]
        return DatabaseOverviewResponse(
            database_url=str(service.config.db_path),
            tables=tables,
            generated_docs=[],
            timestamp=_utc_now(),
        )

    @app.get(
        "/api/database/table/{schema_name}/{table_name}",
        response_model=DatabaseTableDetailResponse,
    )
    def database_table(
        schema_name: str,
        table_name: str,
        limit: int = 25,
        service: ChatService = Depends(resolve_chat_service),
    ) -> DatabaseTableDetailResponse:
        if schema_name not in {"main", "memory"}:
            raise HTTPException(status_code=404, detail=f"Unsupported schema: {schema_name}")
        table_context = _find_table_context(service.stage1_context, table_name)
        sample_columns, sample_rows = _sample_table_rows(
            config=service.config,
            stage1_context=service.stage1_context,
            table_name=table_name,
            limit=limit,
        )
        return DatabaseTableDetailResponse(
            table_schema=table_context.schema_name,
            table_name=table_context.table_name,
            columns=_table_columns(table_context),
            sample_columns=sample_columns,
            sample_rows=sample_rows,
            sample_limit=max(1, min(limit, 500)),
            timestamp=_utc_now(),
        )

    @app.post("/api/database/query", response_model=DatabaseQueryResponse)
    def database_query(
        request: DatabaseQueryRequest,
        service: ChatService = Depends(resolve_chat_service),
    ) -> DatabaseQueryResponse:
        validation = validate_sql(
            request.sql,
            service.stage1_context,
            question="direct database explorer query",
        )
        if not validation.is_valid:
            raise HTTPException(status_code=400, detail="; ".join(validation.errors))
        execution = execute_validated_sql(
            validation,
            db_path=service.config.db_path,
            max_rows=request.limit,
        )
        return DatabaseQueryResponse(
            columns=execution.columns,
            rows=execution.rows,
            row_count=execution.row_count,
            limit=request.limit,
            sql=execution.sql,
            execution_time=execution.elapsed_seconds,
            timestamp=_utc_now(),
            truncated=execution.truncated,
            warnings=validation.warnings,
        )

    @app.post("/api/chat", response_model=ChatbotAnswer)
    def chat(
        request: ChatRequest,
        service: ChatService = Depends(resolve_chat_service),
    ) -> ChatbotAnswer:
        return service.ask(
            request.question,
            show_sql=request.show_sql,
            allow_llm=request.allow_llm,
            show_debug=request.show_debug,
        )

    return app


app = create_app()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="health-system-chatbot-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(
        "health_system_chatbot.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
