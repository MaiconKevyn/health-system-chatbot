from dataclasses import replace

import pytest

from evaluation.chatbot.ablation.variants import (
    VARIANTS,
    apply_config_overrides,
    get_variant,
    parse_variant_names,
    validate_registry,
)
from health_system_chatbot.config import ChatbotConfig


def test_variant_registry_is_valid_and_unique():
    validate_registry()

    assert "full_agent" in VARIANTS
    assert "openai_raw_retrieved_schema" in VARIANTS


def test_parse_variant_names_rejects_unknown_variant():
    with pytest.raises(ValueError, match="Unknown variant"):
        parse_variant_names("full_agent,missing_variant")


def test_parse_variant_names_can_filter_openai_baselines():
    names = parse_variant_names(
        "full_agent,openai_raw_retrieved_schema",
        no_openai_baselines=True,
    )

    assert names == ["full_agent"]


def test_apply_config_overrides_uses_dataclass_copy(tmp_path):
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "db.duckdb",
        openai_api_key=None,
    )
    spec = get_variant("no_self_correction")

    updated = apply_config_overrides(config, spec)

    assert updated.sql_correction_attempts == 0
    assert config.sql_correction_attempts == 2
    assert replace(config) == config
