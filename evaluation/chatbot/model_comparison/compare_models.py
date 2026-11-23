"""Compare LLM models end to end on the sihrd9 question set.

Usage:
    python evaluation/chatbot/model_comparison/compare_models.py \
        --models gpt-5.4-nano gpt-6-luna --reps 2

For each (repetition, question) both models run back to back, so time-of-day
drift affects them equally. Every LLM call made by the pipeline is captured
through pydantic-ai usage (tokens, requests, cost). The executed SQL is re-run
and compared value-by-value with the gold SQL computed on the same database.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
import unicodedata
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import duckdb  # noqa: E402
import pydantic_ai  # noqa: E402

from health_system_chatbot.artifacts import load_stage1_context  # noqa: E402
from health_system_chatbot.config import load_config  # noqa: E402
from health_system_chatbot.workflow import run_chat  # noqa: E402

HERE = Path(__file__).resolve().parent
_USAGE: list = []
_original_run_sync = pydantic_ai.Agent.run_sync


def _recording_run_sync(self, *args, **kwargs):
    result = _original_run_sync(self, *args, **kwargs)
    _USAGE.append((self.name, result.usage))
    return result


pydantic_ai.Agent.run_sync = _recording_run_sync


def _norm(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = unicodedata.normalize("NFKD", str(value))
    return "".join(c for c in text if not unicodedata.combining(c)).strip().lower()


def _same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= max(0.01, 0.005 * abs(a))  # 0.5% tolerance for rates/averages
    return a == b


def _row_contains(actual_row, gold_row) -> bool:
    pool = list(actual_row)
    for g in gold_row:
        hit = next((i for i, a in enumerate(pool) if _same(g, a)), None)
        if hit is None:
            return False
        pool.pop(hit)
    return True


def compare(gold_rows, actual_rows) -> dict:
    gold = [[_norm(v) for v in r] for r in gold_rows]
    actual = [[_norm(v) for v in r] for r in actual_rows]
    contained = all(any(_row_contains(a, g) for a in actual) for g in gold)
    return {"match": contained, "strict": contained and len(actual) == len(gold)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["gpt-5.4-nano", "gpt-6-luna"])
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--out", type=Path, default=HERE / "results.jsonl")
    args = parser.parse_args()

    base = load_config(ROOT)
    ctx = load_stage1_context(base.project_root, db_path=base.db_path)
    questions = json.loads((HERE / "questions_sihrd9.json").read_text(encoding="utf-8"))
    con = duckdb.connect(str(base.db_path), read_only=True)
    gold = {q["id"]: con.execute(q["sql"]).fetchall() for q in questions}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as out:
        for rep in range(1, args.reps + 1):
            for q in questions:
                for model in args.models:
                    # "gpt-6-luna@low" selects a reasoning effort for that run.
                    model_id, _, effort = model.partition("@")
                    config = dataclasses.replace(base, llm_model=model_id, llm_reasoning_effort=effort)
                    _USAGE.clear()
                    started = time.perf_counter()
                    answer = run_chat(
                        q["question"], config=config, stage1_context=ctx,
                        show_sql=True, show_debug=False, allow_llm=True,
                        write_trace=False, write_audit_log=False,
                    )
                    latency = time.perf_counter() - started
                    result = {"match": False, "strict": False}
                    error = None
                    if answer.status == "answered" and answer.sql:
                        try:
                            result = compare(gold[q["id"]], con.execute(answer.sql).fetchmany(500))
                        except Exception as exc:  # noqa: BLE001
                            error = str(exc)[:200]
                    usage = {
                        "requests": sum(u.requests for _, u in _USAGE),
                        "input_tokens": sum(u.input_tokens for _, u in _USAGE),
                        "output_tokens": sum(u.output_tokens for _, u in _USAGE),
                        "cost_usd": float(sum((u.cost or 0) for _, u in _USAGE)),
                        "agents": [name for name, _ in _USAGE],
                    }
                    record = {
                        "rep": rep, "id": q["id"], "model": model, "status": answer.status,
                        "latency_s": round(latency, 2), **result, "error": error, **usage,
                        "sql": answer.sql, "answer": answer.answer_pt[:400],
                    }
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out.flush()
                    print(f"rep{rep} {q['id']} {model:14s} {answer.status:8s} match={result['match']!s:5s} "
                          f"{latency:5.1f}s req={usage['requests']} ${usage['cost_usd']:.5f}", flush=True)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
