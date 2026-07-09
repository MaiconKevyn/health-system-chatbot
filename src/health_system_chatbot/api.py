from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .artifacts import load_stage1_context
from .config import ChatbotConfig, load_config
from .models import ChatbotAnswer, Stage1Context
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


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService.from_environment()


def create_app(*, chat_service: ChatService | None = None) -> FastAPI:
    app = FastAPI(
        title="Health System Chatbot",
        version="0.1.0",
    )

    def resolve_chat_service() -> ChatService:
        return chat_service or get_chat_service()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "health-system-chatbot",
            "fastapi": True,
        }

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
