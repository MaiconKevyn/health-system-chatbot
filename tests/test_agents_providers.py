from pathlib import Path

import pytest

import health_system_chatbot.agents as agents_module
from health_system_chatbot.config import ChatbotConfig


def _config(tmp_path: Path, **overrides) -> ChatbotConfig:
    defaults = dict(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key=None,
    )
    defaults.update(overrides)
    return ChatbotConfig(**defaults)


def test_build_model_openai_returns_responses_model(tmp_path):
    from pydantic_ai.models.openai import OpenAIResponsesModel

    config = _config(tmp_path, llm_provider="openai", openai_api_key="test-openai-key")

    model = agents_module._build_model(config)

    assert isinstance(model, OpenAIResponsesModel)
    assert model.model_name == config.llm_model


def test_build_model_openai_without_key_raises(tmp_path):
    config = _config(tmp_path, llm_provider="openai", openai_api_key=None)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        agents_module._build_model(config)


def test_build_model_anthropic_returns_anthropic_model(tmp_path):
    from pydantic_ai.models.anthropic import AnthropicModel

    config = _config(
        tmp_path,
        llm_provider="anthropic",
        anthropic_api_key="test-anthropic-key",
        llm_model="claude-3-5-sonnet-latest",
    )

    model = agents_module._build_model(config)

    assert isinstance(model, AnthropicModel)
    assert model.model_name == "claude-3-5-sonnet-latest"


def test_build_model_anthropic_without_key_raises(tmp_path):
    config = _config(tmp_path, llm_provider="anthropic", anthropic_api_key=None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        agents_module._build_model(config)


def test_build_model_ollama_returns_openai_chat_model_without_key(tmp_path):
    from pydantic_ai.models.openai import OpenAIChatModel

    config = _config(
        tmp_path,
        llm_provider="ollama",
        ollama_base_url="http://localhost:11434/v1",
        llm_model="llama3.1",
    )

    model = agents_module._build_model(config)

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "llama3.1"
    assert str(model.client.base_url).rstrip("/") == "http://localhost:11434/v1"


def test_build_model_settings_openai_uses_responses_settings(tmp_path):
    config = _config(tmp_path, llm_provider="openai", openai_api_key="test-openai-key")

    settings = agents_module._build_model_settings(config)

    assert settings["temperature"] == 0
    assert "openai_store" in settings


def test_build_model_settings_non_openai_uses_generic_settings(tmp_path):
    config = _config(tmp_path, llm_provider="anthropic", anthropic_api_key="test-anthropic-key")

    settings = agents_module._build_model_settings(config)

    assert settings["temperature"] == 0
    assert settings["max_tokens"] == 8192
    assert "openai_store" not in settings


def test_build_model_unsupported_provider_raises(tmp_path):
    config = _config(tmp_path, llm_provider="openai", openai_api_key="test-openai-key")
    object.__setattr__(config, "llm_provider", "unsupported")

    with pytest.raises(RuntimeError, match="Unsupported LLM provider"):
        agents_module._build_model(config)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_supports_tool_calling_true_for_non_ollama_providers(tmp_path):
    config = _config(tmp_path, llm_provider="openai", openai_api_key="test-openai-key")

    assert agents_module._supports_tool_calling(config) is True


def test_ollama_model_supports_tools_true_when_capability_present(monkeypatch):
    monkeypatch.setattr(
        "httpx.post",
        lambda url, json, timeout: _FakeResponse({"capabilities": ["completion", "tools"]}),
    )

    assert agents_module._ollama_model_supports_tools("http://host-a:11434/v1", "some-model") is True


def test_ollama_model_supports_tools_false_when_completion_only(monkeypatch):
    monkeypatch.setattr(
        "httpx.post",
        lambda url, json, timeout: _FakeResponse({"capabilities": ["completion"]}),
    )

    assert (
        agents_module._ollama_model_supports_tools("http://host-b:11434/v1", "duckdb-nsql:7b")
        is False
    )


def test_ollama_model_supports_tools_fails_open_on_network_error(monkeypatch):
    def _raise(url, json, timeout):
        raise ConnectionError("no server")

    monkeypatch.setattr("httpx.post", _raise)

    assert agents_module._ollama_model_supports_tools("http://host-c:11434/v1", "unreachable") is True


def test_agent_output_type_wraps_in_prompted_output_when_unsupported():
    from pydantic_ai import PromptedOutput

    from health_system_chatbot.models import SqlPlan

    wrapped = agents_module._agent_output_type(SqlPlan, supports_tools=False)
    plain = agents_module._agent_output_type(SqlPlan, supports_tools=True)

    assert isinstance(wrapped, PromptedOutput)
    assert plain is SqlPlan


def test_build_sql_plan_agent_skips_catalog_tools_when_unsupported(tmp_path, monkeypatch):
    from pydantic_ai import PromptedOutput

    called = {"registered": False}
    monkeypatch.setattr(
        "health_system_chatbot.tools.catalog_tools.register_catalog_tools",
        lambda agent: called.__setitem__("registered", True),
    )
    monkeypatch.setattr(agents_module, "_supports_tool_calling", lambda config: False)

    config = _config(
        tmp_path,
        llm_provider="ollama",
        ollama_base_url="http://localhost:11434/v1",
        llm_model="duckdb-nsql:7b",
        catalog_tools_enabled=True,
    )

    agent = agents_module.build_sql_plan_agent(config)

    assert called["registered"] is False
    assert isinstance(agent.output_type, PromptedOutput)


def test_build_sql_plan_agent_registers_catalog_tools_when_supported(tmp_path, monkeypatch):
    called = {"registered": False}
    monkeypatch.setattr(
        "health_system_chatbot.tools.catalog_tools.register_catalog_tools",
        lambda agent: called.__setitem__("registered", True),
    )
    monkeypatch.setattr(agents_module, "_supports_tool_calling", lambda config: True)

    config = _config(
        tmp_path,
        llm_provider="ollama",
        ollama_base_url="http://localhost:11434/v1",
        llm_model="llama3.1",
        catalog_tools_enabled=True,
    )

    agent = agents_module.build_sql_plan_agent(config)

    assert called["registered"] is True
    assert agent.output_type is not None


def test_build_model_reuses_one_client_per_thread_and_config(tmp_path):
    import threading

    config = _config(tmp_path, llm_provider="openai", openai_api_key="test-key")

    first = agents_module._build_model(config)
    second = agents_module._build_model(config)
    other_thread: list[object] = []
    worker = threading.Thread(target=lambda: other_thread.append(agents_module._build_model(config)))
    worker.start()
    worker.join()

    assert first is second
    assert other_thread[0] is not first


def test_openai_settings_apply_configured_reasoning_effort(tmp_path):
    default = agents_module._build_model_settings(
        _config(tmp_path, openai_api_key="k", llm_reasoning_effort="")
    )
    low = agents_module._build_model_settings(
        _config(tmp_path, openai_api_key="k", llm_reasoning_effort="low")
    )

    assert "openai_reasoning_effort" not in default
    assert low["openai_reasoning_effort"] == "low"
