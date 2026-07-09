from pathlib import Path

import pytest

from health_system_chatbot.config import load_config


def _project_root(tmp_path: Path) -> Path:
    (tmp_path / "GOAL.md").write_text("test project root", encoding="utf-8")
    return tmp_path


def test_load_config_exposes_pydantic_ai_defaults(monkeypatch, tmp_path):
    root = _project_root(tmp_path)
    monkeypatch.delenv("CHATBOT_AGENT_FRAMEWORK", raising=False)
    monkeypatch.delenv("CHATBOT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CHATBOT_ENABLE_MULTI_CANDIDATE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = load_config(root)

    assert config.agent_framework == "pydantic_ai"
    assert config.llm_provider == "openai"
    assert config.schema_retrieval_mode == "auto"
    assert config.sql_correction_attempts == 2
    assert config.sql_candidates == 1
    assert config.enable_multi_candidate is False
    assert config.catalog_tools_enabled is True
    assert config.catalog_retrieval_mode == "lexical"
    assert config.safe_summary()["agent_framework"] == "pydantic_ai"
    assert config.safe_summary()["schema_retrieval_mode"] == "auto"
    assert config.safe_summary()["catalog_tools_enabled"] is True
    assert config.safe_summary()["openai_api_key_set"] is False


def test_load_config_accepts_llamaindex_fallback(monkeypatch, tmp_path):
    root = _project_root(tmp_path)
    monkeypatch.setenv("CHATBOT_AGENT_FRAMEWORK", "llamaindex")
    monkeypatch.setenv("CHATBOT_ENABLE_MULTI_CANDIDATE", "true")
    monkeypatch.setenv("CHATBOT_SQL_CANDIDATES", "3")

    config = load_config(root)

    assert config.agent_framework == "llamaindex"
    assert config.enable_multi_candidate is True
    assert config.sql_candidates == 3


def test_load_config_rejects_unknown_agent_framework(monkeypatch, tmp_path):
    root = _project_root(tmp_path)
    monkeypatch.setenv("CHATBOT_AGENT_FRAMEWORK", "unknown")

    with pytest.raises(ValueError, match="CHATBOT_AGENT_FRAMEWORK"):
        load_config(root)


def test_load_config_accepts_catalog_tool_settings(monkeypatch, tmp_path):
    root = _project_root(tmp_path)
    monkeypatch.setenv("CHATBOT_CATALOG_TOOLS_ENABLED", "false")
    monkeypatch.setenv("CHATBOT_CATALOG_RETRIEVAL_MODE", "lexical")
    monkeypatch.setenv("CHATBOT_CATALOG_INDEX_DIR", "catalog-index")

    config = load_config(root)

    assert config.catalog_tools_enabled is False
    assert config.catalog_retrieval_mode == "lexical"
    assert config.catalog_index_dir == root / "catalog-index"


def test_load_config_rejects_unimplemented_catalog_retrieval_mode(monkeypatch, tmp_path):
    root = _project_root(tmp_path)
    monkeypatch.setenv("CHATBOT_CATALOG_RETRIEVAL_MODE", "hybrid")

    with pytest.raises(ValueError, match="CHATBOT_CATALOG_RETRIEVAL_MODE"):
        load_config(root)
