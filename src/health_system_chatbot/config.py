from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_LLM_MODEL = "gpt-4.1-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_AGENT_FRAMEWORK = "pydantic_ai"
DEFAULT_SCHEMA_RETRIEVAL_MODE = "auto"
VALID_LLM_PROVIDERS = {"openai"}
VALID_AGENT_FRAMEWORKS = {"pydantic_ai", "llamaindex"}
VALID_SCHEMA_RETRIEVAL_MODES = {"auto", "keyword", "llamaindex_vector"}


@dataclass(frozen=True)
class ChatbotConfig:
    project_root: Path
    db_path: Path
    openai_api_key: str | None
    llm_model: str = DEFAULT_LLM_MODEL
    embed_model: str = DEFAULT_EMBED_MODEL
    llm_provider: str = DEFAULT_LLM_PROVIDER
    agent_framework: str = DEFAULT_AGENT_FRAMEWORK
    schema_retrieval_mode: str = DEFAULT_SCHEMA_RETRIEVAL_MODE
    max_rows: int = 200
    query_timeout_seconds: int = 60
    sql_correction_attempts: int = 2
    sql_candidates: int = 1
    enable_multi_candidate: bool = False
    index_dir: Path | None = None
    audit_log_path: Path | None = None

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key)

    def safe_summary(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "openai_api_key_set": self.has_openai_key,
            "llm_model": self.llm_model,
            "embed_model": self.embed_model,
            "llm_provider": self.llm_provider,
            "agent_framework": self.agent_framework,
            "schema_retrieval_mode": self.schema_retrieval_mode,
            "max_rows": self.max_rows,
            "query_timeout_seconds": self.query_timeout_seconds,
            "sql_correction_attempts": self.sql_correction_attempts,
            "sql_candidates": self.sql_candidates,
            "enable_multi_candidate": self.enable_multi_candidate,
            "index_dir": str(self.index_dir or self.project_root / ".chatbot_index"),
            "audit_log_path": str(
                self.audit_log_path
                or self.project_root / "evaluation/chatbot/audit/chat_audit.jsonl"
            ),
        }


def find_project_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for path in [cur, *cur.parents]:
        if (path / "chat_goal.md").exists() or (path / "GOAL.md").exists():
            return path
    return cur


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _choice_env(name: str, default: str, allowed: set[str]) -> str:
    value = os.environ.get(name, default).strip().lower()
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {choices}")
    return value


def load_config(project_root: Path | None = None) -> ChatbotConfig:
    root = find_project_root(project_root)
    load_dotenv(root / ".env")

    db_path = Path(os.environ.get("CHATBOT_DB_PATH", "sihrd5.duckdb"))
    if not db_path.is_absolute():
        db_path = root / db_path

    index_dir = Path(os.environ.get("CHATBOT_INDEX_DIR", ".chatbot_index"))
    if not index_dir.is_absolute():
        index_dir = root / index_dir

    audit_log_path = Path(
        os.environ.get("CHATBOT_AUDIT_LOG_PATH", "evaluation/chatbot/audit/chat_audit.jsonl")
    )
    if not audit_log_path.is_absolute():
        audit_log_path = root / audit_log_path

    return ChatbotConfig(
        project_root=root,
        db_path=db_path,
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        llm_model=os.environ.get("CHATBOT_LLM_MODEL", DEFAULT_LLM_MODEL),
        embed_model=os.environ.get("CHATBOT_EMBED_MODEL", DEFAULT_EMBED_MODEL),
        llm_provider=_choice_env("CHATBOT_LLM_PROVIDER", DEFAULT_LLM_PROVIDER, VALID_LLM_PROVIDERS),
        agent_framework=_choice_env(
            "CHATBOT_AGENT_FRAMEWORK",
            DEFAULT_AGENT_FRAMEWORK,
            VALID_AGENT_FRAMEWORKS,
        ),
        schema_retrieval_mode=_choice_env(
            "CHATBOT_SCHEMA_RETRIEVAL_MODE",
            DEFAULT_SCHEMA_RETRIEVAL_MODE,
            VALID_SCHEMA_RETRIEVAL_MODES,
        ),
        max_rows=_int_env("CHATBOT_MAX_ROWS", 200),
        query_timeout_seconds=_int_env("CHATBOT_QUERY_TIMEOUT_SECONDS", 60),
        sql_correction_attempts=_int_env("CHATBOT_SQL_CORRECTION_ATTEMPTS", 2),
        sql_candidates=_int_env("CHATBOT_SQL_CANDIDATES", 1),
        enable_multi_candidate=_bool_env("CHATBOT_ENABLE_MULTI_CANDIDATE", False),
        index_dir=index_dir,
        audit_log_path=audit_log_path,
    )
