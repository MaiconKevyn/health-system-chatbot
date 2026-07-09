from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from health_system_chatbot.config import ChatbotConfig

from .contracts import VariantSpec


VARIANTS: dict[str, VariantSpec] = {
    "full_agent": VariantSpec(
        name="full_agent",
        kind="agent",
        description="Current Pydantic AI pipeline with all configured components.",
    ),
    "no_catalog_tools": VariantSpec(
        name="no_catalog_tools",
        kind="agent",
        description="Agent run without CID/procedure/dimension catalog tools.",
        config_overrides={"catalog_tools_enabled": False},
    ),
    "no_context_enrichment": VariantSpec(
        name="no_context_enrichment",
        kind="agent",
        description="Agent run with raw schema retrieval and no enrichment.",
        config_overrides={"context_enrichment_enabled": False},
    ),
    "no_self_correction": VariantSpec(
        name="no_self_correction",
        kind="agent",
        description="Agent run without SQL self-correction/refiner attempts.",
        config_overrides={"sql_correction_attempts": 0},
    ),
    "single_candidate": VariantSpec(
        name="single_candidate",
        kind="agent",
        description="Agent run forced to one SQL candidate.",
        config_overrides={"enable_multi_candidate": False, "sql_candidates": 1},
    ),
    "multi_candidate": VariantSpec(
        name="multi_candidate",
        kind="agent",
        description="Agent run forced to three SQL candidates.",
        config_overrides={"enable_multi_candidate": True, "sql_candidates": 3},
    ),
    "keyword_schema_only": VariantSpec(
        name="keyword_schema_only",
        kind="agent",
        description="Agent run with keyword schema retrieval.",
        config_overrides={"schema_retrieval_mode": "keyword"},
    ),
    "llamaindex_schema_retrieval": VariantSpec(
        name="llamaindex_schema_retrieval",
        kind="agent",
        description="Agent run with LlamaIndex vector schema retrieval.",
        config_overrides={"schema_retrieval_mode": "llamaindex_vector"},
    ),
    "no_llm_generation": VariantSpec(
        name="no_llm_generation",
        kind="control",
        description="Control run with model generation disabled.",
        allow_llm=False,
    ),
    "openai_raw_minimal_schema": VariantSpec(
        name="openai_raw_minimal_schema",
        kind="openai_baseline",
        description="Direct OpenAI SQL generation with compact table/column context.",
        baseline_mode="minimal_schema",
    ),
    "openai_raw_retrieved_schema": VariantSpec(
        name="openai_raw_retrieved_schema",
        kind="openai_baseline",
        description="Direct OpenAI SQL generation with the retrieved schema context.",
        baseline_mode="retrieved_schema",
    ),
    "openai_raw_full_context": VariantSpec(
        name="openai_raw_full_context",
        kind="openai_baseline",
        description="Direct OpenAI SQL generation with enriched context and examples.",
        baseline_mode="full_context",
    ),
    "openai_raw_one_retry": VariantSpec(
        name="openai_raw_one_retry",
        kind="openai_baseline",
        description="Direct OpenAI SQL generation with one validation/execution retry.",
        baseline_mode="one_retry",
    ),
}


def list_variants() -> list[str]:
    return sorted(VARIANTS)


def get_variant(name: str) -> VariantSpec:
    try:
        return VARIANTS[name]
    except KeyError as exc:
        choices = ", ".join(list_variants())
        raise ValueError(f"Unknown ablation variant: {name}. Available variants: {choices}") from exc


def parse_variant_names(raw: str | None, *, no_openai_baselines: bool = False) -> list[str]:
    names = [part.strip() for part in (raw or "full_agent").split(",") if part.strip()]
    if not names:
        raise ValueError("At least one variant is required.")
    unknown = [name for name in names if name not in VARIANTS]
    if unknown:
        choices = ", ".join(list_variants())
        raise ValueError(f"Unknown variant(s): {', '.join(unknown)}. Available variants: {choices}")
    if no_openai_baselines:
        names = [name for name in names if VARIANTS[name].kind != "openai_baseline"]
    if not names:
        raise ValueError("No variants left to run after applying filters.")
    return names


def apply_config_overrides(config: ChatbotConfig, spec: VariantSpec) -> ChatbotConfig:
    if not spec.config_overrides:
        return config
    return replace(config, **spec.config_overrides)


def validate_registry(variants: Iterable[VariantSpec] = VARIANTS.values()) -> None:
    seen: set[str] = set()
    for variant in variants:
        if variant.name in seen:
            raise ValueError(f"Duplicate variant name: {variant.name}")
        seen.add(variant.name)
        if variant.kind == "openai_baseline" and not variant.baseline_mode:
            raise ValueError(f"OpenAI baseline variant requires baseline_mode: {variant.name}")
