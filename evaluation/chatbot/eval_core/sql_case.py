from __future__ import annotations

import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
ERROR_TAXONOMY_VERSION = "2.0.0"

from health_system_chatbot.config import ChatbotConfig
from health_system_chatbot.models import GroundTruthItem, RetrievedContext, Stage1Context
from health_system_chatbot.sql_validator import validate_sql
from health_system_chatbot.result_probes import probe_result_contract
from evaluation.chatbot.evaluate_extraction_accuracy import _safe_sql_for_evaluation_fallback

from .comparison import compare_results, comparison_mode_for
from .error_taxonomy import categorize_execution_error, categorize_validation_error
from .execution import execute_sql


def preview_values(rows: list[tuple[Any, ...]], max_rows: int = 10) -> list[list[Any]]:
    return [list(row) for row in rows[:max_rows]]


def build_empty_record(item: GroundTruthItem, *, variant: str, strategy: str) -> dict[str, Any]:
    return {
        "variant": variant,
        "strategy": strategy,
        "id": item.id,
        "difficulty": item.difficulty,
        "expected_result_type": item.expected_result_type,
        "question_pt": item.question_pt,
        "benchmark_status": item.benchmark_status,
        "template_family": item.template_family or item.id,
        "intent_status": "answerable",
        "retrieval_mode": None,
        "retrieved_tables": [],
        "retrieved_columns_count": 0,
        "business_metrics": [],
        "value_hints_count": 0,
        "catalog_candidates_count": 0,
        "catalog_candidate_labels": [],
        "catalog_tool_calls_count": 0,
        "catalog_tools": [],
        "tool_calls": [],
        "tool_budget": {},
        "catalog_decisions_count": 0,
        "catalog_decisions": [],
        "query_examples": [],
        "query_examples_enabled_effective": False,
        "example_bank_version": "unversioned",
        "semantic_rules_version": "unversioned",
        "retrieved_example_ids": [],
        "example_retrieval_decisions": [],
        "rejected_example_ids": [],
        "question_contract": None,
        "semantic_rule_ids": [],
        "assumptions_used": [],
        "validator_findings": {},
        "join_probe_stats": [],
        "stop_reason": None,
        "semantic_match": False,
        "presentation_match": False,
        "error_taxonomy_version": ERROR_TAXONOMY_VERSION,
        "plan_source": strategy,
        "candidate_count": 1,
        "selected_candidate_id": None,
        "candidate_selection_reason": "",
        "candidate_selection_correct": None,
        "candidates": [],
        "correction_attempts": [],
        "correction_success": False,
        "generated_sql": "",
        "ground_truth_sql": item.sql,
        "generated_sql_valid": False,
        "generated_sql_validation_errors": [],
        "generated_sql_validation_warnings": [],
        "generated_execution_status": "skipped",
        "ground_truth_execution_status": "skipped",
        "comparison_mode": comparison_mode_for(item),
        "result_match": False,
        "alias_only_difference": False,
        "type_only_difference": False,
        "order_only_mismatch": False,
        "shape_match": False,
        "contained_in_actual": False,
        "contained_in_expected": False,
        "semantic_label_equivalence": False,
        "expected_columns": [],
        "actual_columns": [],
        "expected_preview_values": [],
        "actual_preview_values": [],
        "expected_row_count": 0,
        "actual_row_count": 0,
        "expected_truncated": False,
        "actual_truncated": False,
        "error_category": None,
        "error_message": None,
        "latency_seconds": 0.0,
        "token_usage": None,
        "estimated_cost_usd": None,
    }


def fill_retrieval_metadata(record: dict[str, Any], retrieved: RetrievedContext | None) -> None:
    if retrieved is None:
        return
    record["retrieval_mode"] = retrieved.retrieval_mode
    record["retrieved_tables"] = retrieved.tables
    record["retrieved_columns_count"] = len(retrieved.columns)
    record["business_metrics"] = [metric.name for metric in retrieved.business_metrics]
    record["value_hints_count"] = len(retrieved.value_hints)
    record["catalog_candidates_count"] = len(retrieved.catalog_candidates)
    record["catalog_candidate_labels"] = [
        candidate.label for candidate in retrieved.catalog_candidates[:12]
    ]
    record["catalog_tool_calls_count"] = len(retrieved.catalog_tool_calls)
    record["catalog_tools"] = [call.tool for call in retrieved.catalog_tool_calls]
    record["tool_calls"] = [call.model_dump() for call in retrieved.catalog_tool_calls]
    record["query_examples"] = [example.id for example in retrieved.query_examples]
    record["retrieved_example_ids"] = list(record["query_examples"])
    record["query_examples_enabled_effective"] = bool(retrieved.query_examples)
    record["example_retrieval_decisions"] = [
        decision.model_dump() for decision in retrieved.example_retrieval_decisions
    ]
    record["rejected_example_ids"] = [
        decision.example_id
        for decision in retrieved.example_retrieval_decisions
        if not decision.accepted
    ]
    record["question_contract"] = (
        retrieved.question_contract.model_dump()
        if retrieved.question_contract is not None
        else None
    )
    record["semantic_rule_ids"] = retrieved.semantic_rule_ids
    record["assumptions_used"] = retrieved.assumptions_used


def evaluate_generated_sql(
    item: GroundTruthItem,
    *,
    variant: str,
    strategy: str,
    generated_sql: str | None,
    config: ChatbotConfig,
    ctx: Stage1Context,
    retrieved: RetrievedContext | None,
    max_rows: int,
    timeout_seconds: int,
    numeric_tolerance: float,
    token_usage: dict[str, Any] | None = None,
    estimated_cost_usd: float | None = None,
    generation_error: str | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    record = build_empty_record(item, variant=variant, strategy=strategy)
    record["example_bank_version"] = ctx.example_bank_version
    record["semantic_rules_version"] = ctx.semantic_rules_version
    record["tool_budget"] = {
        "catalog_calls": config.catalog_tool_call_budget,
        "duplicate_signature": config.catalog_duplicate_call_limit,
        "agent_requests": config.agent_request_limit,
    }
    record["token_usage"] = token_usage
    record["estimated_cost_usd"] = estimated_cost_usd
    fill_retrieval_metadata(record, retrieved)
    try:
        expected = execute_sql(
            item.sql,
            db_path=config.db_path,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
        )
        record["ground_truth_execution_status"] = expected.status
        record["expected_columns"] = expected.columns
        record["expected_row_count"] = expected.row_count
        record["expected_truncated"] = expected.truncated
        record["expected_preview_values"] = preview_values(expected.rows)
        if expected.status != "passed":
            record["error_category"] = "environment_error"
            record["error_message"] = (
                "Ground truth SQL failed against the configured database: "
                f"{expected.error_message}"
            )
            return record

        if generation_error:
            if generation_error.startswith("required_source_unavailable:"):
                record["error_category"] = "required_source_unavailable"
                record["stop_reason"] = "required_source_unavailable"
            elif "catalog_tool_budget_exceeded" in generation_error or "catalog_duplicate_call" in generation_error:
                record["error_category"] = "catalog_budget_exceeded"
                record["stop_reason"] = "catalog_budget_exceeded"
            else:
                record["error_category"] = "provider_error"
            record["error_message"] = generation_error
            return record
        if not generated_sql:
            record["error_category"] = "invalid_sql"
            record["error_message"] = "Strategy did not return SQL."
            return record

        record["generated_sql"] = generated_sql
        validation = validate_sql(
            generated_sql,
            ctx,
            question=item.question_pt,
            question_contract=(retrieved.question_contract if retrieved else None),
            db_path=config.db_path,
        )
        record["generated_sql_valid"] = validation.is_valid
        record["generated_sql_validation_errors"] = validation.errors
        record["generated_sql_validation_warnings"] = validation.warnings
        record["validator_findings"] = {
            "errors": validation.errors,
            "warnings": validation.warnings,
            "findings": validation.findings,
            "probe_stats": validation.probe_stats,
        }
        record["join_probe_stats"] = list(validation.probe_stats)
        executable_sql = _safe_sql_for_evaluation_fallback(generated_sql, validation)
        if not executable_sql:
            record["error_category"] = categorize_validation_error(validation.errors)
            record["error_message"] = "; ".join(validation.errors)
            return record
        if not validation.is_valid:
            record["generated_sql_valid"] = True
            record["generated_sql_validation_warnings"] = [
                *record["generated_sql_validation_warnings"],
                "Static validation was overridden by evaluation fallback; DuckDB execution is authoritative for this run.",
            ]

        actual = execute_sql(
            executable_sql,
            db_path=config.db_path,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
        )
        record["generated_execution_status"] = actual.status
        record["actual_columns"] = actual.columns
        record["actual_row_count"] = actual.row_count
        record["actual_truncated"] = actual.truncated
        record["actual_preview_values"] = preview_values(actual.rows)
        if actual.status != "passed":
            record["error_category"] = categorize_execution_error(actual.error_message)
            record["error_message"] = actual.error_message
            return record

        result_probe = probe_result_contract(
            contract=(retrieved.question_contract if retrieved else None),
            columns=actual.columns,
            rows=actual.rows,
            truncated=actual.truncated,
        )
        record["validator_findings"]["result_probes"] = result_probe.findings
        if result_probe.warnings:
            record["generated_sql_validation_warnings"].extend(result_probe.warnings)
        if result_probe.errors:
            record["error_category"] = "result_contract_violation"
            record["error_message"] = "; ".join(result_probe.errors)
            return record

        comparison = compare_results(
            expected.columns,
            expected.rows,
            actual.columns,
            actual.rows,
            mode=comparison_mode_for(item),
            numeric_tolerance=numeric_tolerance,
            expected_truncated=expected.truncated,
            actual_truncated=actual.truncated,
            required_output_concepts=item.required_output_concepts,
            optional_output_concepts=item.optional_output_concepts,
            representation=item.representation,
        )
        record["result_match"] = comparison.result_match
        record["alias_only_difference"] = comparison.alias_only_difference
        record["type_only_difference"] = comparison.type_only_difference
        record["order_only_mismatch"] = comparison.order_only_mismatch
        record["shape_match"] = comparison.shape_match
        record["contained_in_actual"] = comparison.contained_in_actual
        record["contained_in_expected"] = comparison.contained_in_expected
        record["semantic_label_equivalence"] = comparison.semantic_label_equivalence
        record["semantic_match"] = comparison.semantic_match
        record["presentation_match"] = comparison.presentation_match
        record["error_category"] = comparison.error_category
        record["error_message"] = comparison.error_message
        return record
    except Exception as exc:
        record["error_category"] = "environment_error"
        record["error_message"] = str(exc)
        return record
    finally:
        record["latency_seconds"] = time.perf_counter() - start
