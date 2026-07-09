from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import GroundTruthItem, Stage1Context

from .contracts import SharedEvalContext
from .reports import write_ablation_outputs
from .strategies import build_strategy
from .variants import get_variant
from ..eval_core.sql_case import build_empty_record


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class AblationRunOptions:
    run_id: str
    run_dir: Path
    run_config: dict[str, Any]
    variant_names: list[str]
    max_rows: int
    timeout_seconds: int
    numeric_tolerance: float
    cache_openai: bool = False
    fail_fast: bool = False


def _operational_error_record(
    *,
    item: GroundTruthItem,
    variant: str,
    strategy: str,
    error: Exception,
) -> dict[str, Any]:
    record = build_empty_record(item, variant=variant, strategy=strategy)
    record["error_category"] = "environment_error"
    record["error_message"] = str(error)
    return record


def run_ablation(
    *,
    config: ChatbotConfig,
    stage1_context: Stage1Context,
    items: list[GroundTruthItem],
    options: AblationRunOptions,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    shared_context = SharedEvalContext(
        config=config,
        stage1_context=stage1_context,
        max_rows=options.max_rows,
        timeout_seconds=options.timeout_seconds,
        numeric_tolerance=options.numeric_tolerance,
        cache_openai=options.cache_openai,
        cache_dir=str(options.run_dir / "cache/openai") if options.cache_openai else None,
    )
    records: list[dict[str, Any]] = []
    total = len(items) * len(options.variant_names)
    completed = 0
    started = time.perf_counter()

    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    for variant_name in options.variant_names:
        spec = get_variant(variant_name)
        strategy = build_strategy(spec)
        emit(f"[variant] {variant_name}: {spec.description}")
        for item in items:
            completed += 1
            emit(f"[{completed}/{total}] {variant_name}/{item.id} running...")
            try:
                record = strategy.run_item(item, context=shared_context)
            except Exception as exc:
                record = _operational_error_record(
                    item=item,
                    variant=variant_name,
                    strategy=strategy.name,
                    error=exc,
                )
                if options.fail_fast:
                    raise
            records.append(record)
            emit(
                "[{done}/{total}] {variant}/{item_id} done match={match} "
                "valid={valid} exec={exec_status} error={error}".format(
                    done=completed,
                    total=total,
                    variant=variant_name,
                    item_id=item.id,
                    match=record.get("result_match"),
                    valid=record.get("generated_sql_valid"),
                    exec_status=record.get("generated_execution_status"),
                    error=record.get("error_category") or "none",
                )
            )

    run_config = dict(options.run_config)
    run_config["elapsed_seconds"] = time.perf_counter() - started
    return write_ablation_outputs(
        run_dir=options.run_dir,
        run_id=options.run_id,
        run_config=run_config,
        records=records,
    )
