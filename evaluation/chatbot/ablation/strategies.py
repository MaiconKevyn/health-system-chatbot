from __future__ import annotations

from time import perf_counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from evaluation.chatbot.evaluate_extraction_accuracy import evaluate_item
from health_system_chatbot.models import GroundTruthItem
from health_system_chatbot.schema_context import retrieve_context

from .baseline_openai import (
    build_baseline_prompt,
    build_retry_prompt,
    generate_sql_with_openai,
)
from .contracts import EvaluationStrategy, SharedEvalContext, VariantSpec
from .variants import apply_config_overrides
from ..eval_core.sql_case import evaluate_generated_sql


class PydanticAgentStrategy(EvaluationStrategy):
    def __init__(self, spec: VariantSpec) -> None:
        self.spec = spec
        self.name = spec.name

    def run_item(
        self,
        item: GroundTruthItem,
        *,
        context: SharedEvalContext,
    ) -> dict[str, Any]:
        variant_config = apply_config_overrides(context.config, self.spec)
        record = evaluate_item(
            item,
            config=variant_config,
            ctx=context.stage1_context,
            allow_llm=self.spec.allow_llm,
            max_rows=context.max_rows,
            timeout_seconds=context.timeout_seconds,
            numeric_tolerance=context.numeric_tolerance,
        )
        record["variant"] = self.spec.name
        record["strategy"] = "pydantic_agent"
        record["variant_description"] = self.spec.description
        record["config_overrides"] = self.spec.config_overrides
        record["feature_flags"] = self.spec.feature_flags
        return record


class OpenAIDirectStrategy(EvaluationStrategy):
    def __init__(self, spec: VariantSpec) -> None:
        self.spec = spec
        self.name = spec.name

    def _cache_dir(self, context: SharedEvalContext) -> Path | None:
        if not context.cache_openai:
            return None
        if context.cache_dir:
            return Path(context.cache_dir)
        return context.config.project_root / "evaluation/chatbot/cache/openai_baselines"

    def run_item(
        self,
        item: GroundTruthItem,
        *,
        context: SharedEvalContext,
    ) -> dict[str, Any]:
        started = perf_counter()
        mode = self.spec.baseline_mode or "retrieved_schema"
        baseline_config = replace(
            context.config,
            context_enrichment_enabled=(mode in {"full_context", "one_retry"}),
        )
        retrieved = retrieve_context(
            item.question_pt,
            context.stage1_context,
            config=baseline_config,
        )
        prompt = build_baseline_prompt(
            question=item.question_pt,
            retrieved=retrieved,
            stage1_context=context.stage1_context,
            mode=mode,
        )
        cache_dir = self._cache_dir(context)
        generation = generate_sql_with_openai(
            prompt=prompt,
            config=baseline_config,
            cache_dir=cache_dir,
            use_cache=context.cache_openai,
        )
        record = evaluate_generated_sql(
            item,
            variant=self.spec.name,
            strategy="openai_direct",
            generated_sql=generation.sql,
            config=baseline_config,
            ctx=context.stage1_context,
            retrieved=retrieved,
            max_rows=context.max_rows,
            timeout_seconds=context.timeout_seconds,
            numeric_tolerance=context.numeric_tolerance,
            token_usage=generation.usage,
            estimated_cost_usd=generation.estimated_cost_usd,
            generation_error=generation.error,
        )
        record["variant_description"] = self.spec.description
        record["baseline_mode"] = mode
        record["raw_model_response"] = generation.raw_text
        record["openai_cache_hit"] = generation.cache_hit
        record["latency_seconds"] = perf_counter() - started

        should_retry = (
            mode == "one_retry"
            and bool(record.get("generated_sql"))
            and record.get("error_category") is not None
        )
        if not should_retry:
            return record

        retry_prompt = build_retry_prompt(
            original_prompt=prompt,
            previous_sql=str(record["generated_sql"]),
            error_message=str(record.get("error_message") or record.get("error_category")),
        )
        retry_generation = generate_sql_with_openai(
            prompt=retry_prompt,
            config=baseline_config,
            cache_dir=cache_dir,
            use_cache=context.cache_openai,
        )
        retry_record = evaluate_generated_sql(
            item,
            variant=self.spec.name,
            strategy="openai_direct_retry",
            generated_sql=retry_generation.sql,
            config=baseline_config,
            ctx=context.stage1_context,
            retrieved=retrieved,
            max_rows=context.max_rows,
            timeout_seconds=context.timeout_seconds,
            numeric_tolerance=context.numeric_tolerance,
            token_usage=retry_generation.usage,
            estimated_cost_usd=retry_generation.estimated_cost_usd,
            generation_error=retry_generation.error,
        )
        retry_record["variant_description"] = self.spec.description
        retry_record["baseline_mode"] = mode
        retry_record["raw_model_response"] = retry_generation.raw_text
        retry_record["openai_cache_hit"] = retry_generation.cache_hit
        retry_record["latency_seconds"] = perf_counter() - started
        retry_record["correction_attempts"] = [
            {
                "attempt": 1,
                "phase": "openai_direct_retry",
                "input_sql": record.get("generated_sql"),
                "input_error": record.get("error_message"),
                "sql": retry_record.get("generated_sql"),
                "success": retry_record.get("generated_execution_status") == "passed",
            }
        ]
        retry_record["correction_success"] = (
            retry_record.get("generated_execution_status") == "passed"
            and retry_record.get("error_category") is None
        )
        retry_record["first_attempt"] = record
        return retry_record


def build_strategy(spec: VariantSpec) -> EvaluationStrategy:
    if spec.kind in {"agent", "control"}:
        return PydanticAgentStrategy(spec)
    if spec.kind == "openai_baseline":
        return OpenAIDirectStrategy(spec)
    raise ValueError(f"Unsupported variant kind: {spec.kind}")
