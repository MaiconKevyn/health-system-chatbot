from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@dataclass(frozen=True)
class EvalItem:
    id: str
    question: str
    gold_sql: str
    difficulty: str
    expected_result_type: str


@dataclass(frozen=True)
class QueryResult:
    ok: bool
    columns: list[str]
    rows: list[list[Any]]
    error: str = ""
    elapsed_s: float = 0.0


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _safe_sql(sql: str) -> str:
    cleaned = re.sub(r"--.*?$", "", sql or "", flags=re.MULTILINE).strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", cleaned):
        raise ValueError("Only SELECT/WITH SQL is allowed")
    forbidden = re.compile(
        r"(?is)\b(insert|update|delete|create|drop|alter|truncate|copy|attach|detach|pragma)\b"
    )
    if forbidden.search(cleaned):
        raise ValueError("SQL contains a forbidden statement")
    return cleaned


def _execute_sql(db_path: Path, sql: str, *, max_rows: int) -> QueryResult:
    start = time.perf_counter()
    try:
        cleaned = _safe_sql(sql)
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            cursor = con.execute(cleaned)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(max_rows + 1)
        finally:
            con.close()
        return QueryResult(
            ok=True,
            columns=columns,
            rows=[[_normalize_value(value) for value in row] for row in rows[:max_rows]],
            elapsed_s=time.perf_counter() - start,
        )
    except Exception as exc:
        return QueryResult(
            ok=False,
            columns=[],
            rows=[],
            error=str(exc),
            elapsed_s=time.perf_counter() - start,
        )


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        try:
            return math.isclose(float(left), float(right), rel_tol=1e-6, abs_tol=1e-6)
        except Exception:
            return False
    return left == right


def _rows_equal(left: list[list[Any]], right: list[list[Any]]) -> bool:
    if len(left) != len(right):
        return False
    for left_row, right_row in zip(left, right, strict=True):
        if len(left_row) != len(right_row):
            return False
        if any(not _values_equal(a, b) for a, b in zip(left_row, right_row, strict=True)):
            return False
    return True


def _row_sort_key(row: list[Any]) -> str:
    return json.dumps(row, ensure_ascii=True, sort_keys=True, default=_json_default)


def _content_match(gold: QueryResult, predicted: QueryResult, expected_type: str) -> bool:
    if not gold.ok or not predicted.ok:
        return False
    if len(gold.rows) == 1 and len(gold.rows[0]) == 1 and predicted.rows:
        return len(predicted.rows[0]) == 1 and _values_equal(gold.rows[0][0], predicted.rows[0][0])
    ordered_types = {"ordered", "time_series", "ranked", "top_n"}
    if expected_type in ordered_types:
        return _rows_equal(gold.rows, predicted.rows)
    return _rows_equal(sorted(gold.rows, key=_row_sort_key), sorted(predicted.rows, key=_row_sort_key))


def _strict_match(gold: QueryResult, predicted: QueryResult, expected_type: str) -> bool:
    return (
        gold.ok
        and predicted.ok
        and gold.columns == predicted.columns
        and _content_match(gold, predicted, expected_type)
    )


def _answer_contains_scalar(answer: str, gold: QueryResult) -> bool | None:
    if not gold.ok or len(gold.rows) != 1 or len(gold.rows[0]) != 1:
        return None
    value = gold.rows[0][0]
    if not isinstance(value, (int, float)):
        return None
    variants = {str(value)}
    if isinstance(value, int):
        variants.add(f"{value:,}".replace(",", "."))
        variants.add(f"{value:,}")
    else:
        variants.add(f"{value:.2f}".replace(".", ","))
        variants.add(f"{value:.2f}")
    compact_answer = (answer or "").replace("\xa0", " ")
    return any(variant in compact_answer for variant in variants)


def _load_items(path: Path) -> list[EvalItem]:
    items: list[EvalItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        item_id = str(raw.get("id") or raw.get("qid") or len(items) + 1)
        question = str(raw.get("question_pt") or raw.get("question") or "")
        gold_sql = str(raw.get("sql") or raw.get("query") or "")
        if not question or not gold_sql:
            continue
        items.append(
            EvalItem(
                id=item_id,
                question=question,
                gold_sql=gold_sql,
                difficulty=str(raw.get("difficulty") or "unknown"),
                expected_result_type=str(raw.get("expected_result_type") or ""),
            )
        )
    return items


def _select_items(
    items: list[EvalItem],
    *,
    ids: set[str] | None,
    limit: int | None,
    stratified: bool,
) -> list[EvalItem]:
    if ids:
        items = [item for item in items if item.id in ids]
    if limit is None or limit >= len(items):
        return items
    if not stratified:
        return items[:limit]

    by_difficulty: dict[str, list[EvalItem]] = defaultdict(list)
    for item in items:
        by_difficulty[item.difficulty].append(item)
    selected: list[EvalItem] = []
    difficulties = sorted(by_difficulty)
    cursor = 0
    while len(selected) < limit and any(by_difficulty.values()):
        difficulty = difficulties[cursor % len(difficulties)]
        bucket = by_difficulty[difficulty]
        if bucket:
            selected.append(bucket.pop(0))
        cursor += 1
    return selected


def _run_pydantic_items(items: list[EvalItem]) -> list[dict[str, Any]]:
    from health_system_chatbot.artifacts import load_stage1_context
    from health_system_chatbot.config import load_config
    from health_system_chatbot.workflow import run_chat

    config = load_config(ROOT)
    ctx = load_stage1_context(config.project_root, db_path=config.db_path)
    outputs: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        start = time.perf_counter()
        try:
            answer = run_chat(
                item.question,
                config=config,
                stage1_context=ctx,
                show_sql=True,
                show_debug=False,
                allow_llm=True,
                write_trace=False,
                write_audit_log=False,
            )
            outputs.append(
                {
                    "id": item.id,
                    "status": answer.status,
                    "success": answer.status == "answered",
                    "sql": answer.sql,
                    "answer": answer.answer_pt,
                    "error": "",
                    "elapsed_s": time.perf_counter() - start,
                }
            )
        except Exception as exc:
            outputs.append(
                {
                    "id": item.id,
                    "status": "error",
                    "success": False,
                    "sql": "",
                    "answer": "",
                    "error": str(exc),
                    "elapsed_s": time.perf_counter() - start,
                }
            )
        print(f"pydantic_ai [{index:03d}/{len(items):03d}] {item.id}", flush=True)
    return outputs


def _run_langgraph_worker(args: argparse.Namespace) -> int:
    langgraph_root = Path(args.langgraph_root).resolve()
    sys.path.insert(0, str(langgraph_root))
    os.chdir(langgraph_root)
    load_dotenv(langgraph_root / ".env")

    from src.agent.llm_manager import OpenAILLMManager
    from src.agent.simple_agent import SimpleSQLAgent
    from src.application.config.simple_config import ApplicationConfig

    items = _load_items(Path(args.dataset))
    ids = set(args.ids.split(",")) if args.ids else None
    items = _select_items(items, ids=ids, limit=args.limit, stratified=args.stratified)

    manager = OpenAILLMManager(ApplicationConfig())
    agent = SimpleSQLAgent(manager)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for index, item in enumerate(items, 1):
            start = time.perf_counter()
            try:
                result = agent.run(item.question, session_id=f"comparison_{item.id}")
                row = {
                    "id": item.id,
                    "status": result.get("answerability") or ("answered" if result.get("success") else "failed"),
                    "success": bool(result.get("success")),
                    "sql": result.get("sql_query") or "",
                    "answer": result.get("response") or "",
                    "error": result.get("error_message") or "",
                    "elapsed_s": time.perf_counter() - start,
                }
            except Exception as exc:
                row = {
                    "id": item.id,
                    "status": "error",
                    "success": False,
                    "sql": "",
                    "answer": "",
                    "error": str(exc),
                    "elapsed_s": time.perf_counter() - start,
                }
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")
            handle.flush()
            print(f"langgraph_simple [{index:03d}/{len(items):03d}] {item.id}", flush=True)
    return 0


def _run_langgraph_items(items: list[EvalItem], args: argparse.Namespace) -> list[dict[str, Any]]:
    langgraph_python = Path(args.langgraph_root) / ".venv/bin/python"
    if not langgraph_python.exists():
        raise FileNotFoundError(f"LangGraph venv not found: {langgraph_python}")

    selected_ids = ",".join(item.id for item in items)
    with tempfile.TemporaryDirectory(prefix="agent_comparison_") as tmp:
        output = Path(tmp) / "langgraph_outputs.jsonl"
        cmd = [
            str(langgraph_python),
            str(Path(__file__).resolve()),
            "--langgraph-worker",
            "--dataset",
            str(Path(args.dataset).resolve()),
            "--output",
            str(output),
            "--langgraph-root",
            str(Path(args.langgraph_root).resolve()),
            "--ids",
            selected_ids,
        ]
        subprocess.run(cmd, cwd=args.langgraph_root, check=True)
        return [
            json.loads(line)
            for line in output.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _evaluate_agent_outputs(
    *,
    agent_name: str,
    items: list[EvalItem],
    outputs: list[dict[str, Any]],
    gold_results: dict[str, QueryResult],
    db_path: Path,
    max_rows: int,
) -> list[dict[str, Any]]:
    output_by_id = {str(row["id"]): row for row in outputs}
    records: list[dict[str, Any]] = []
    for item in items:
        output = output_by_id.get(item.id, {})
        predicted = (
            _execute_sql(db_path, output.get("sql") or "", max_rows=max_rows)
            if output.get("sql")
            else QueryResult(ok=False, columns=[], rows=[], error="empty_sql")
        )
        gold = gold_results[item.id]
        content_match = _content_match(gold, predicted, item.expected_result_type)
        strict_match = _strict_match(gold, predicted, item.expected_result_type)
        answer_scalar_match = _answer_contains_scalar(output.get("answer") or "", gold)
        records.append(
            {
                "agent": agent_name,
                "id": item.id,
                "difficulty": item.difficulty,
                "question": item.question,
                "gold_success": gold.ok,
                "gold_error": gold.error,
                "agent_success": bool(output.get("success")),
                "agent_status": output.get("status"),
                "sql_generated": bool(output.get("sql")),
                "generated_sql": output.get("sql") or "",
                "prediction_success": predicted.ok,
                "prediction_error": predicted.error,
                "content_match": bool(content_match) if gold.ok else None,
                "strict_match": bool(strict_match) if gold.ok else None,
                "answer_scalar_match": answer_scalar_match,
                "gold_columns": gold.columns,
                "predicted_columns": predicted.columns,
                "gold_rows_sample": gold.rows[:5],
                "predicted_rows_sample": predicted.rows[:5],
                "gold_row_count": len(gold.rows),
                "predicted_row_count": len(predicted.rows),
                "agent_elapsed_s": output.get("elapsed_s"),
                "sql_elapsed_s": predicted.elapsed_s,
                "answer": output.get("answer") or "",
                "agent_error": output.get("error") or "",
            }
        )
    return records


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    gold_records = [record for record in records if record["gold_success"]]
    scalar_answer_records = [
        record for record in gold_records if record["answer_scalar_match"] is not None
    ]
    by_difficulty: dict[str, dict[str, Any]] = {}
    for difficulty in sorted({record["difficulty"] for record in records}):
        subset = [record for record in records if record["difficulty"] == difficulty]
        gold_subset = [record for record in subset if record["gold_success"]]
        by_difficulty[difficulty] = {
            "total": len(subset),
            "gold_success": len(gold_subset),
            "content_match_rate": _rate(gold_subset, "content_match"),
            "sql_execution_rate": _rate(gold_subset, "prediction_success"),
        }
    failure_categories = Counter()
    for record in gold_records:
        if record["content_match"]:
            continue
        if not record["sql_generated"]:
            failure_categories["empty_sql"] += 1
        elif not record["prediction_success"]:
            failure_categories["sql_execution_error"] += 1
        elif record["predicted_row_count"] != record["gold_row_count"]:
            failure_categories["row_count_mismatch"] += 1
        elif record["predicted_columns"] != record["gold_columns"]:
            failure_categories["content_or_alias_mismatch"] += 1
        else:
            failure_categories["content_mismatch"] += 1
    return {
        "total": total,
        "gold_success_rate": sum(r["gold_success"] for r in records) / total if total else 0,
        "agent_success_rate": sum(r["agent_success"] for r in records) / total if total else 0,
        "sql_generated_rate": sum(r["sql_generated"] for r in gold_records) / len(gold_records)
        if gold_records
        else 0,
        "sql_execution_rate": _rate(gold_records, "prediction_success"),
        "content_match_rate": _rate(gold_records, "content_match"),
        "strict_match_rate": _rate(gold_records, "strict_match"),
        "scalar_answer_match_rate": _rate(scalar_answer_records, "answer_scalar_match"),
        "scalar_answer_items": len(scalar_answer_records),
        "avg_agent_elapsed_s": sum(float(r["agent_elapsed_s"] or 0) for r in records) / total
        if total
        else 0,
        "by_difficulty": by_difficulty,
        "failure_categories": dict(failure_categories),
    }


def _rate(records: list[dict[str, Any]], key: str) -> float | None:
    if not records:
        return None
    return sum(record.get(key) is True for record in records) / len(records)


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "agent",
        "id",
        "difficulty",
        "gold_success",
        "agent_success",
        "sql_generated",
        "prediction_success",
        "content_match",
        "strict_match",
        "answer_scalar_match",
        "gold_row_count",
        "predicted_row_count",
        "agent_elapsed_s",
        "prediction_error",
        "agent_error",
        "question",
        "generated_sql",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in fields})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evaluation/ground_truth/cid_disease_tooling_eval.jsonl")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", default="")
    parser.add_argument("--stratified", action="store_true")
    parser.add_argument("--max-rows", type=int, default=1000)
    parser.add_argument("--skip-pydantic", action="store_true")
    parser.add_argument("--skip-langgraph", action="store_true")
    parser.add_argument("--langgraph-root", default="/Users/maiconkevyn/PycharmProjects/agent-txt2sql-langgraph")
    parser.add_argument("--langgraph-worker", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    if args.langgraph_worker:
        return _run_langgraph_worker(args)

    load_dotenv(ROOT / ".env")
    from health_system_chatbot.config import load_config

    config = load_config(ROOT)
    dataset = (ROOT / args.dataset).resolve() if not Path(args.dataset).is_absolute() else Path(args.dataset)
    items = _load_items(dataset)
    ids = set(args.ids.split(",")) if args.ids else None
    items = _select_items(items, ids=ids, limit=args.limit, stratified=args.stratified)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) if args.output_dir else ROOT / "evaluation/chatbot/results" / f"agent_comparison_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    gold_results = {
        item.id: _execute_sql(config.db_path, item.gold_sql, max_rows=args.max_rows) for item in items
    }

    all_records: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    if not args.skip_pydantic:
        pydantic_outputs = _run_pydantic_items(items)
        records = _evaluate_agent_outputs(
            agent_name="pydantic_ai",
            items=items,
            outputs=pydantic_outputs,
            gold_results=gold_results,
            db_path=config.db_path,
            max_rows=args.max_rows,
        )
        all_records.extend(records)
        summaries["pydantic_ai"] = _summarize(records)

    if not args.skip_langgraph:
        langgraph_outputs = _run_langgraph_items(items, args)
        records = _evaluate_agent_outputs(
            agent_name="langgraph_simple",
            items=items,
            outputs=langgraph_outputs,
            gold_results=gold_results,
            db_path=config.db_path,
            max_rows=args.max_rows,
        )
        all_records.extend(records)
        summaries["langgraph_simple"] = _summarize(records)

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset),
        "items": len(items),
        "db_path": str(config.db_path),
        "max_rows": args.max_rows,
        "summaries": summaries,
        "records": all_records,
    }
    (output_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    _write_csv(output_dir / "summary.csv", all_records)
    print(json.dumps({"output_dir": str(output_dir), "summaries": summaries}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
