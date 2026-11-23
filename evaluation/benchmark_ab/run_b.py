"""Adapter for system B (text-to-sql-chatbot / agent-text-to-sql-sus). Run with B's venv.

    cd <snapshot>/B && <B venv>/bin/python <this file> <gt.jsonl> <out.jsonl> [--workers N] [--ids ...]

Each worker builds one `TextToSQLAgent` and calls `ask(question)` without
history: value linking, SQL generation, execution with repair and the final
natural-language answer — the same path as B's own evaluation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

_STATE: dict = {}
DB = "/Users/maiconkevyn/PycharmProjects/databases/sihrd9.duckdb"


def _init(effort: str) -> None:
    os.environ["DATABASE_PATH"] = DB
    os.environ["SQL_MODEL"] = "gpt-6-luna"
    os.environ["ANSWER_MODEL"] = "gpt-6-luna"
    os.environ["BENCH_REASONING_EFFORT"] = effort  # honoured by the snapshot patch of src/llm.py
    sys.path.insert(0, str(Path.cwd()))
    import warnings

    warnings.filterwarnings("ignore")
    from src.agent import TextToSQLAgent

    _STATE["agent"] = TextToSQLAgent()


def _answer(item: dict) -> dict:
    t = time.time()
    out = {"id": item["id"], "question": item["question"], "system": "B"}
    try:
        r = _STATE["agent"].ask(item["question"])
        out.update(
            status="answered" if (r.answerable and r.result is not None) else ("refused" if not r.answerable else "failed"),
            answer=r.answer,
            sql=r.sql or "",
            refused=not r.answerable,
            caveats=r.assumptions,
            meta={"attempts": r.attempts, "errors": r.errors,
                  "row_count": len(r.result.rows) if r.result is not None else None},
        )
    except Exception as exc:  # noqa: BLE001
        out.update(status="error", answer="", sql="", refused=True,
                   error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()[-2000:])
    out["latency_s"] = round(time.time() - t, 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("gt")
    ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--ids", nargs="*")
    args = ap.parse_args()

    items = [json.loads(line) for line in open(args.gt, encoding="utf-8")]
    if args.ids:
        items = [i for i in items if i["id"] in set(args.ids)]
    out_path = Path(args.out)
    done = set()
    if out_path.exists():
        done = {json.loads(line)["id"] for line in out_path.open(encoding="utf-8") if line.strip()}
    todo = [i for i in items if i["id"] not in done]
    print(f"B: {len(todo)} to run ({len(done)} already done)", flush=True)

    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init, initargs=(args.effort,)) as ex, \
            out_path.open("a", encoding="utf-8") as fh:
        futures = {ex.submit(_answer, {"id": i["id"], "question": i["question"]}): i["id"] for i in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            print(f"B [{n}/{len(todo)}] {rec['id']} {rec['status']} {rec['latency_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
