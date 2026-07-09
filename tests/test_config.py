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

    config = load_config(root)

    assert config.agent_framework == "pydantic_ai"
    assert config.llm_provider == "openai"
    assert config.schema_retrieval_mode == "auto"
    assert config.sql_correction_attempts == 2
    assert config.sql_candidates == 1
    assert config.enable_multi_candidate is False
    assert config.safe_summary()["agent_framework"] == "pydantic_ai"
    assert config.safe_summary()["schema_retrieval_mode"] == "auto"
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
