from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ..eval_core.error_taxonomy import next_action_for
from .metrics import group_by_variant, numeric_rate, summarize_by_variant
from ..eval_core.summaries import write_json_payload


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


def build_summary_payload(
    *,
    run_id: str,
    run_config: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    variant_summaries = summarize_by_variant(records)
    full_rate = numeric_rate(variant_summaries.get("full_agent", {}), "result_match_rate")
    variants = []
    for name, summary in variant_summaries.items():
        result_rate = numeric_rate(summary, "result_match_rate")
        variants.append(
            {
                "variant": name,
                "total": summary.get("total", 0),
                "result_match_rate": result_rate,
                "comparable_result_match_rate": summary.get(
                    "comparable_result_match_rate"
                ),
                "delta_vs_full_agent_pp": (
                    round((result_rate - full_rate) * 100, 4)
                    if result_rate is not None and full_rate is not None
                    else None
                ),
                "sql_valid_rate": summary.get("sql_valid_rate"),
                "sql_execution_rate": summary.get("sql_execution_rate"),
                "latency_p50": summary.get("latency_p50"),
                "latency_p95": summary.get("latency_p95"),
                "contained_in_actual_count": summary.get("contained_in_actual_count", 0),
                "contained_in_expected_count": summary.get("contained_in_expected_count", 0),
                "semantic_label_equivalence_count": summary.get(
                    "semantic_label_equivalence_count", 0
                ),
                "error_category_counts": summary.get("error_category_counts", {}),
            }
        )
    variants.sort(
        key=lambda item: (
            item["result_match_rate"] is None,
            -(item["result_match_rate"] or 0),
            item["variant"],
        )
    )
    return {
        "run_id": run_id,
        "run_config": run_config,
        "variant_summaries": variant_summaries,
        "variant_ranking": variants,
    }


def _records_by_id(records: list[dict[str, Any]], variant: str) -> dict[str, dict[str, Any]]:
    return {
        record["id"]: record
        for record in records
        if record.get("variant") == variant
    }


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant": record.get("variant"),
        "id": record.get("id"),
        "difficulty": record.get("difficulty"),
        "question_pt": record.get("question_pt"),
        "result_match": record.get("result_match"),
        "error_category": record.get("error_category"),
        "error_message": record.get("error_message"),
        "contained_in_actual": record.get("contained_in_actual"),
        "contained_in_expected": record.get("contained_in_expected"),
        "semantic_label_equivalence": record.get("semantic_label_equivalence"),
        "generated_sql": record.get("generated_sql"),
        "ground_truth_sql": record.get("ground_truth_sql"),
        "retrieved_tables": record.get("retrieved_tables", []),
        "latency_seconds": record.get("latency_seconds"),
    }


def build_failure_sets(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = group_by_variant(records)
    full = _records_by_id(records, "full_agent")
    baseline_wins = []
    full_agent_wins = []
    regressions = []
    for variant, variant_records in grouped.items():
        if variant == "full_agent":
            continue
        for record in variant_records:
            full_record = full.get(record["id"])
            if full_record is None:
                continue
            variant_match = bool(record.get("result_match"))
            full_match = bool(full_record.get("result_match"))
            if variant.startswith("openai_") and variant_match and not full_match:
                baseline_wins.append(
                    {"baseline": _compact_record(record), "full_agent": _compact_record(full_record)}
                )
            if full_match and not variant_match:
                payload = {"variant": _compact_record(record), "full_agent": _compact_record(full_record)}
                if variant.startswith("openai_"):
                    full_agent_wins.append(payload)
                else:
                    regressions.append(payload)

    validation_failures = [
        _compact_record(record)
        for record in records
        if record.get("generated_sql") and not record.get("generated_sql_valid")
    ]
    execution_failures = [
        _compact_record(record)
        for record in records
        if record.get("generated_sql_valid")
        and record.get("generated_execution_status") not in {"passed", "skipped"}
    ]
    return {
        "baseline_wins": baseline_wins,
        "full_agent_wins": full_agent_wins,
        "regressions_vs_full_agent": regressions,
        "validation_failures": validation_failures,
        "execution_failures": execution_failures,
    }


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, default=_json_default))
            handle.write("\n")


def write_summary_csv(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "variant",
        "total",
        "result_match_rate",
        "comparable_result_match_rate",
        "delta_vs_full_agent_pp",
        "sql_valid_rate",
        "sql_execution_rate",
        "latency_p50",
        "latency_p95",
        "contained_in_actual_count",
        "contained_in_expected_count",
        "semantic_label_equivalence_count",
        "error_category_counts",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in payload["variant_ranking"]:
            writer.writerow(
                {
                    **row,
                    "error_category_counts": json.dumps(
                        row.get("error_category_counts", {}),
                        ensure_ascii=True,
                        default=_json_default,
                    ),
                }
            )


def write_analysis(payload: dict[str, Any], failure_sets: dict[str, list[dict[str, Any]]], path: Path) -> None:
    lines = [
        "# Ablation and OpenAI Baseline Evaluation",
        "",
        f"- Run ID: `{payload['run_id']}`",
        f"- Dataset: `{payload['run_config'].get('dataset')}`",
        f"- Variants: `{payload['run_config'].get('variants')}`",
        "",
        "## Variant Ranking",
        "",
        "| variant | end-to-end match | comparable match | delta vs full pp | valid SQL | execution | p50 latency | p95 latency | gt in generated | generated in gt | semantic labels |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["variant_ranking"]:
        lines.append(
            "| {variant} | {match} | {comparable_match} | {delta} | {valid} | {exec_rate} | {p50} | {p95} | {contained_actual} | {contained_expected} | {semantic_labels} |".format(
                variant=row["variant"],
                match=row["result_match_rate"],
                comparable_match=row["comparable_result_match_rate"],
                delta=row["delta_vs_full_agent_pp"],
                valid=row["sql_valid_rate"],
                exec_rate=row["sql_execution_rate"],
                p50=row["latency_p50"],
                p95=row["latency_p95"],
                contained_actual=row["contained_in_actual_count"],
                contained_expected=row["contained_in_expected_count"],
                semantic_labels=row["semantic_label_equivalence_count"],
            )
        )
    lines.extend(["", "## Error Categories", ""])
    for variant, summary in payload["variant_summaries"].items():
        categories = summary.get("error_category_counts") or {}
        if not categories:
            continue
        lines.extend([f"### {variant}", "", "| category | count | next action |", "| --- | ---: | --- |"])
        for category, count in sorted(categories.items()):
            lines.append(f"| `{category}` | {count} | {next_action_for(category)} |")
        lines.append("")

    lines.extend(
        [
            "## Head-to-Head Sets",
            "",
            f"- Baseline wins over full agent: {len(failure_sets['baseline_wins'])}",
            f"- Full agent wins over OpenAI baselines: {len(failure_sets['full_agent_wins'])}",
            f"- Ablation regressions vs full agent: {len(failure_sets['regressions_vs_full_agent'])}",
            f"- Validation failures: {len(failure_sets['validation_failures'])}",
            f"- Execution failures: {len(failure_sets['execution_failures'])}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ablation_outputs(
    *,
    run_dir: Path,
    run_id: str,
    run_config: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = build_summary_payload(run_id=run_id, run_config=run_config, records=records)
    failure_sets = build_failure_sets(records)
    write_json_payload(run_config, run_dir / "run_config.json")
    write_json_payload(payload, run_dir / "summary.json")
    write_summary_csv(payload, run_dir / "summary.csv")
    write_analysis(payload, failure_sets, run_dir / "analysis.md")
    write_jsonl(records, run_dir / "trace.jsonl")
    for name, variant_records in group_by_variant(records).items():
        variant_dir = run_dir / "variants" / name
        variant_dir.mkdir(parents=True, exist_ok=True)
        write_json_payload(
            {
                "variant": name,
                "summary": payload["variant_summaries"][name],
                "records": variant_records,
            },
            variant_dir / "results.json",
        )
        write_jsonl(variant_records, variant_dir / "trace.jsonl")
    for name, items in failure_sets.items():
        write_jsonl(items, run_dir / "failures" / f"{name}.jsonl")
    return payload
