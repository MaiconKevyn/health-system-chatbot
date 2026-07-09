from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from health_system_chatbot.artifacts import load_stage1_context
from health_system_chatbot.config import load_config
from health_system_chatbot.workflow import run_chat


DEFAULT_DATASET = PROJECT_ROOT / "evaluation/chatbot/chart_eval_questions.jsonl"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "evaluation/chatbot/results"


def _read_jsonl(path: Path, *, limit: int | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            records.append(json.loads(stripped))
            if limit is not None and len(records) >= limit:
                break
    return records


def _contains_internal_details(answer: str) -> bool:
    lowered = answer.lower()
    markers = (
        "select ",
        " from ",
        "where ",
        "detalhe tecnico",
        "base da metrica",
        "caveat",
        "contexto anterior",
        "sql",
    )
    return any(marker in lowered for marker in markers)


def _evaluate_record(record: dict[str, Any], *, config: Any, stage1_context: Any, allow_llm: bool) -> dict[str, Any]:
    started = perf_counter()
    answer = run_chat(
        record["question"],
        config=config,
        stage1_context=stage1_context,
        show_sql=True,
        show_debug=True,
        allow_llm=allow_llm,
        write_trace=False,
        write_audit_log=False,
    )
    elapsed = perf_counter() - started
    payload = answer.model_dump()
    chart = payload.get("chart")
    spec = chart.get("spec") if chart else None
    echarts = chart.get("echarts") if chart else None
    expected_chart_requested = bool(record.get("expected_chart_requested"))
    expected_chart_type = record.get("expected_chart_type")
    actual_chart_type = spec.get("chart_type") if spec else None
    chart_requested = bool(chart and chart.get("requested"))
    chartable = bool(spec and spec.get("chartable"))
    echarts_present = bool(echarts)
    if expected_chart_type == "table":
        chart_type_match = bool(spec and not spec.get("chartable"))
    elif expected_chart_type:
        chart_type_match = actual_chart_type == expected_chart_type
    else:
        chart_type_match = actual_chart_type is None

    return {
        "id": record["id"],
        "question": record["question"],
        "difficulty": record.get("difficulty"),
        "expected_chart_requested": expected_chart_requested,
        "expected_chart_type": expected_chart_type,
        "status": payload.get("status"),
        "latency_seconds": elapsed,
        "answer_pt": payload.get("answer_pt"),
        "sql": payload.get("sql"),
        "chart_requested": chart_requested,
        "chartable": chartable,
        "chart_type": actual_chart_type,
        "echarts_present": echarts_present,
        "chart_type_match": chart_type_match,
        "row_count": (payload.get("evidence") or {}).get("row_count"),
        "answer_has_internal_details": _contains_internal_details(payload.get("answer_pt") or ""),
        "warnings": (payload.get("developer_context") or {}).get("warnings", []),
        "chart_warnings": (payload.get("developer_context") or {}).get("chart_warnings", []),
    }


def _rate(records: list[dict[str, Any]], predicate) -> float:
    if not records:
        return 0.0
    return sum(1 for record in records if predicate(record)) / len(records)


def _build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    chart_cases = [record for record in results if record["expected_chart_requested"]]
    no_chart_cases = [record for record in results if not record["expected_chart_requested"]]
    return {
        "total": len(results),
        "chart_cases": len(chart_cases),
        "no_chart_regression_cases": len(no_chart_cases),
        "answer_success_rate": _rate(results, lambda item: item["status"] == "answered"),
        "chart_payload_rate": _rate(chart_cases, lambda item: item["chart_requested"]),
        "chartable_rate": _rate(chart_cases, lambda item: item["chartable"]),
        "echarts_option_rate": _rate(chart_cases, lambda item: item["echarts_present"]),
        "chart_type_match_rate": _rate(chart_cases, lambda item: item["chart_type_match"]),
        "no_chart_regression_pass_rate": _rate(
            no_chart_cases,
            lambda item: item["status"] == "answered" and not item["chart_requested"],
        ),
        "no_internal_details_in_answer_rate": _rate(
            results,
            lambda item: not item["answer_has_internal_details"],
        ),
        "average_latency_seconds": (
            sum(item["latency_seconds"] for item in results) / len(results)
            if results
            else 0.0
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate chart generation and no-chart regressions."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(PROJECT_ROOT)
    stage1_context = load_stage1_context(config.project_root, db_path=config.db_path)
    records = _read_jsonl(args.dataset, limit=args.limit)

    results = [
        _evaluate_record(
            record,
            config=config,
            stage1_context=stage1_context,
            allow_llm=not args.no_llm,
        )
        for record in records
    ]
    payload = {
        "run_id": args.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset),
        "model": config.llm_model,
        "summary": _build_summary(results),
        "results": results,
    }

    args.results_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.results_dir / f"chart_generation_{args.run_id}.json"
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, default=str),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output_path), "summary": payload["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
