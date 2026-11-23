from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# One model for every LLM stage (SQL plan, repair, chart plan, answer).
# gpt-6-luna with low reasoning beat gpt-5.4-nano on accuracy and cost in
# evaluation/chatbot/model_comparison; gpt-5.4-nano shuts down 2027-04-01.
DEFAULT_LLM_MODEL = "gpt-6-luna"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_AGENT_FRAMEWORK = "pydantic_ai"
DEFAULT_SCHEMA_RETRIEVAL_MODE = "auto"
DEFAULT_CATALOG_RETRIEVAL_MODE = "lexical"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
# Resolved against the project root; the SIH/SUS DuckDB lives next to the repo.
DEFAULT_DB_PATH = "../databases/sihrd9.duckdb"
VALID_LLM_PROVIDERS = {"openai", "anthropic", "ollama"}
VALID_AGENT_FRAMEWORKS = {"pydantic_ai", "llamaindex"}
VALID_SCHEMA_RETRIEVAL_MODES = {"auto", "keyword", "llamaindex_vector"}
VALID_CATALOG_RETRIEVAL_MODES = {"lexical"}
VALID_REASONING_EFFORTS = {"", "none", "minimal", "low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class ChatbotConfig:
    project_root: Path
    db_path: Path
    openai_api_key: str | None
    llm_model: str = DEFAULT_LLM_MODEL
    # Empty string keeps the provider's default reasoning effort.
    llm_reasoning_effort: str = DEFAULT_REASONING_EFFORT
    embed_model: str = DEFAULT_EMBED_MODEL
    llm_provider: str = DEFAULT_LLM_PROVIDER
    agent_framework: str = DEFAULT_AGENT_FRAMEWORK
    anthropic_api_key: str | None = None
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_api_key: str | None = None
    schema_retrieval_mode: str = DEFAULT_SCHEMA_RETRIEVAL_MODE
    max_rows: int = 200
    query_timeout_seconds: int = 60
    sql_timeout_seconds: int = 30
    sql_correction_attempts: int = 2
    sql_candidates: int = 1
    enable_multi_candidate: bool = False
    context_enrichment_enabled: bool = True
    query_examples_enabled: bool = True
    catalog_tools_enabled: bool = True
    catalog_retrieval_mode: str = DEFAULT_CATALOG_RETRIEVAL_MODE
    catalog_tool_call_budget: int = 8
    catalog_duplicate_call_limit: int = 1
    agent_request_limit: int = 20
    index_dir: Path | None = None
    catalog_index_dir: Path | None = None
    audit_log_path: Path | None = None

    chat_engine: str = "auto"

    @property
    def active_chat_engine(self) -> str:
        if self.chat_engine != "auto":
            return self.chat_engine
        if self.llm_provider == "openai" and self.agent_framework == "pydantic_ai":
            return "sus"
        return "legacy"

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def llm_provider_ready(self) -> bool:
        if self.llm_provider == "openai":
            return self.has_openai_key
        if self.llm_provider == "anthropic":
            return self.has_anthropic_key
        if self.llm_provider == "ollama":
            return bool(self.ollama_base_url)
        return False

    def safe_summary(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "openai_api_key_set": self.has_openai_key,
            "anthropic_api_key_set": self.has_anthropic_key,
            "ollama_base_url": self.ollama_base_url,
            "llm_model": self.llm_model,
            "llm_reasoning_effort": self.llm_reasoning_effort or "provider_default",
            "embed_model": self.embed_model,
            "llm_provider": self.llm_provider,
            "agent_framework": self.agent_framework,
            "chat_engine": self.active_chat_engine,
            "schema_retrieval_mode": self.schema_retrieval_mode,
            "max_rows": self.max_rows,
            "query_timeout_seconds": self.query_timeout_seconds,
            "sql_timeout_seconds": self.sql_timeout_seconds,
            "sql_correction_attempts": self.sql_correction_attempts,
            "sql_candidates": self.sql_candidates,
            "enable_multi_candidate": self.enable_multi_candidate,
            "context_enrichment_enabled": self.context_enrichment_enabled,
            "query_examples_enabled": self.query_examples_enabled,
            "catalog_tools_enabled": self.catalog_tools_enabled,
            "catalog_retrieval_mode": self.catalog_retrieval_mode,
            "catalog_tool_call_budget": self.catalog_tool_call_budget,
            "catalog_duplicate_call_limit": self.catalog_duplicate_call_limit,
            "agent_request_limit": self.agent_request_limit,
            "index_dir": str(self.index_dir or self.project_root / ".chatbot_index"),
            "catalog_index_dir": str(
                self.catalog_index_dir or self.project_root / ".chatbot_catalog_index"
            ),
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

    db_path = Path(os.environ.get("CHATBOT_DB_PATH", DEFAULT_DB_PATH))
    if not db_path.is_absolute():
        db_path = (root / db_path).resolve()

    index_dir = Path(os.environ.get("CHATBOT_INDEX_DIR", ".chatbot_index"))
    if not index_dir.is_absolute():
        index_dir = root / index_dir

    catalog_index_dir = Path(os.environ.get("CHATBOT_CATALOG_INDEX_DIR", ".chatbot_catalog_index"))
    if not catalog_index_dir.is_absolute():
        catalog_index_dir = root / catalog_index_dir

    audit_log_path = Path(
        os.environ.get("CHATBOT_AUDIT_LOG_PATH", "evaluation/chatbot/audit/chat_audit.jsonl")
    )
    if not audit_log_path.is_absolute():
        audit_log_path = root / audit_log_path

    ollama_base_url = (
        os.environ.get("CHATBOT_OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_BASE_URL")
        or DEFAULT_OLLAMA_BASE_URL
    )
    ollama_api_key = os.environ.get("CHATBOT_OLLAMA_API_KEY") or os.environ.get("OLLAMA_API_KEY")

    return ChatbotConfig(
        project_root=root,
        db_path=db_path,
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        chat_engine=_choice_env("CHATBOT_CHAT_ENGINE", "auto", {"auto", "sus", "legacy"}),
        llm_model=os.environ.get("CHATBOT_LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_reasoning_effort=_choice_env(
            "CHATBOT_LLM_REASONING_EFFORT", DEFAULT_REASONING_EFFORT, VALID_REASONING_EFFORTS
        ),
        embed_model=os.environ.get("CHATBOT_EMBED_MODEL", DEFAULT_EMBED_MODEL),
        llm_provider=_choice_env("CHATBOT_LLM_PROVIDER", DEFAULT_LLM_PROVIDER, VALID_LLM_PROVIDERS),
        agent_framework=_choice_env(
            "CHATBOT_AGENT_FRAMEWORK",
            DEFAULT_AGENT_FRAMEWORK,
            VALID_AGENT_FRAMEWORKS,
        ),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        ollama_base_url=ollama_base_url,
        ollama_api_key=ollama_api_key,
        schema_retrieval_mode=_choice_env(
            "CHATBOT_SCHEMA_RETRIEVAL_MODE",
            DEFAULT_SCHEMA_RETRIEVAL_MODE,
            VALID_SCHEMA_RETRIEVAL_MODES,
        ),
        max_rows=_int_env("CHATBOT_MAX_ROWS", 200),
        query_timeout_seconds=_int_env("CHATBOT_QUERY_TIMEOUT_SECONDS", 60),
        sql_timeout_seconds=_int_env("CHATBOT_SQL_TIMEOUT_SECONDS", 30),
        sql_correction_attempts=_int_env("CHATBOT_SQL_CORRECTION_ATTEMPTS", 2),
        sql_candidates=_int_env("CHATBOT_SQL_CANDIDATES", 1),
        enable_multi_candidate=_bool_env("CHATBOT_ENABLE_MULTI_CANDIDATE", False),
        context_enrichment_enabled=_bool_env("CHATBOT_CONTEXT_ENRICHMENT_ENABLED", True),
        query_examples_enabled=_bool_env("CHATBOT_QUERY_EXAMPLES_ENABLED", True),
        catalog_tools_enabled=_bool_env("CHATBOT_CATALOG_TOOLS_ENABLED", True),
        catalog_retrieval_mode=_choice_env(
            "CHATBOT_CATALOG_RETRIEVAL_MODE",
            DEFAULT_CATALOG_RETRIEVAL_MODE,
            VALID_CATALOG_RETRIEVAL_MODES,
        ),
        catalog_tool_call_budget=_int_env("CHATBOT_CATALOG_TOOL_CALL_BUDGET", 8),
        catalog_duplicate_call_limit=_int_env("CHATBOT_CATALOG_DUPLICATE_CALL_LIMIT", 1),
        agent_request_limit=_int_env("CHATBOT_AGENT_REQUEST_LIMIT", 20),
        index_dir=index_dir,
        catalog_index_dir=catalog_index_dir,
        audit_log_path=audit_log_path,
    )
