"""Run paired fresh chats; invoke with the health-system-chatbot venv."""

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from decimal import Decimal
from itertools import permutations
from pathlib import Path
from unittest.mock import patch

import duckdb
from openai._base_client import BaseClient

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODEL = "gpt-6-luna"


def dump(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def same_rows(actual, expected, decimals, ordered):
    if len(actual) != len(expected) or not expected:
        return False

    def normalize(value):
        if isinstance(value, (int, float, Decimal)):
            number = Decimal(str(value))
            return number.quantize(Decimal(1).scaleb(-decimals)) if decimals else number
        return str(value).strip().casefold()

    target = [tuple(map(normalize, row)) for row in expected]
    if any(len(row) != len(target[0]) for row in actual):
        return False
    for order in permutations(range(len(target[0]))):
        rows = [tuple(normalize(row[i]) for i in order) for row in actual]
        if rows == target or (
            not ordered and sorted(rows, key=str) == sorted(target, key=str)
        ):
            return True
    return False


def run_health(question, cfg, context, *, integrated=False):
    if integrated:
        from health_system_chatbot import chat as engine
        trace_writer = "write_observability_record"
    else:
        from health_system_chatbot import workflow as engine
        trace_writer = "_write_observability_record"

    captured = {}

    def capture(config, trace, **kwargs):
        for step in trace["steps"]:
            if step["name"] == "execution":
                captured.update(step["payload"])

    with patch.object(engine, trace_writer, capture):
        answer = engine.run_chat(
            question,
            config=cfg,
            stage1_context=context,
            show_sql=True,
            write_trace=False,
            write_audit_log=False,
        )
    columns = captured.get("columns", [])
    rows = [[r[c] for c in columns] for r in captured.get("rows", [])]
    spec = answer.chart.spec if answer.chart else None
    chart = None
    if spec and spec.chartable and answer.chart.echarts:
        chart = {
            "type": spec.chart_type,
            "points": [[r[spec.x], r[spec.y]] for r in spec.data],
        }
    return {
        "status": answer.status,
        "answer": answer.answer_pt,
        "sql": answer.sql,
        "rows": rows,
        "columns": columns,
        "truncated": captured.get("truncated", False),
        "chart": chart,
    }


def run_sus(question, agent):
    result = {
        "status": "failed",
        "answer": "",
        "sql": "",
        "rows": [],
        "columns": [],
        "chart": None,
        "truncated": False,
    }
    for event in agent.ask_stream(question):
        kind = event["type"]
        if kind == "sql":
            result["sql"] = event["sql"]
        elif kind == "result":
            table = event["result"]
            result.update({key: table[key] for key in ("columns", "rows", "truncated")})
        elif kind == "chart":
            chart = event["chart"]
            x, y = [result["columns"].index(chart[k]) for k in ("x", "y")]
            result["chart"] = {
                "type": chart["kind"],
                "points": [[r[x], r[y]] for r in result["rows"]],
            }
        elif kind == "token":
            result["answer"] += event["text"]
        elif kind == "failure":
            result["error"] = event.get("message")
        elif kind == "done" and result["rows"] and result["answer"]:
            result["status"] = "answered"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sus-root", type=Path, default=ROOT.parent / "text-to-sql-chatbot"
    )
    parser.add_argument("--cases", type=Path, default=HERE / "cases.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--with-integrated", action="store_true")
    parser.add_argument(
        "--first-rep", type=int, default=1, help="First repetition number (one-based)"
    )
    args = parser.parse_args()
    if args.first_rep < 1:
        parser.error("--first-rep must be positive")
    if args.reps < 1:
        parser.error("--reps must be positive")
    args.out.mkdir(parents=True, exist_ok=False)
    os.environ.update(SQL_MODEL=MODEL, ANSWER_MODEL=MODEL, PYDANTIC_AI_NO_BANNER="1")
    sys.path[:0] = [str(args.sus_root.resolve()), str(ROOT / "src")]
    from health_system_chatbot.artifacts import load_stage1_context
    from health_system_chatbot.config import load_config

    cfg = load_config(ROOT)
    os.environ["DATABASE_PATH"] = str(cfg.db_path)
    from src.agent import TextToSQLAgent
    from src.config import settings

    assert settings.answer_model == settings.sql_model == MODEL
    cases = json.loads(args.cases.read_text())
    with duckdb.connect(str(cfg.db_path), read_only=True) as con:
        gold = {c["id"]: con.execute(c["sql"]).fetchall() for c in cases}
    assert all(gold.values())
    (args.out / "gold.json").write_text(dump(gold))

    def revision(root):
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()

    meta = {
        "model": MODEL,
        "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "reasoning": "low",
        "database": str(cfg.db_path),
        "database_bytes": cfg.db_path.stat().st_size,
        "database_mtime_ns": cfg.db_path.stat().st_mtime_ns,
        "reps": args.reps,
        "first_rep": args.first_rep,
        "seed": 745,
        "health_head": revision(ROOT),
        "sus_head": revision(args.sus_root),
        "working_trees": True,
        "projects": ["health", "sus", "integrated"] if args.with_integrated else ["health", "sus"],
    }
    (args.out / "manifest.json").write_text(dump(meta))
    context = load_stage1_context(ROOT, db_path=cfg.db_path)
    agent = TextToSQLAgent()
    requests = []
    builder = BaseClient._build_request

    def checked(client, options, **kwargs):
        body = dict(options.json_data or {})
        if body.get("model") != MODEL:
            raise RuntimeError(f"Unexpected model: {body.get('model')}")
        if options.url.endswith("/responses"):
            body["reasoning"] = {**(body.get("reasoning") or {}), "effort": "low"}
        elif options.url.endswith("/chat/completions"):
            body["reasoning_effort"] = "low"
        else:
            raise RuntimeError(f"Unexpected model endpoint: {options.url}")
        requests.append(
            {"endpoint": options.url, "model": body["model"], "effort": "low"}
        )
        return builder(client, options.model_copy(update={"json_data": body}), **kwargs)

    with (
        tempfile.TemporaryDirectory() as tmp,
        patch.object(BaseClient, "_build_request", checked),
        (args.out / "results.jsonl").open("x") as out,
    ):
        cfg = replace(
            cfg,
            llm_model=MODEL,
            llm_provider="openai",
            llm_reasoning_effort="low",
            agent_framework="pydantic_ai",
            schema_retrieval_mode="keyword",
            audit_log_path=Path(tmp) / "empty.jsonl",
        )
        for rep in range(args.first_rep - 1, args.first_rep - 1 + args.reps):
            order = cases.copy()
            random.Random(745 + rep).shuffle(order)
            for case in order:
                idx = cases.index(case)
                systems = (
                    ["health", "sus"] if (idx + rep) % 2 == 0 else ["sus", "health"]
                )
                if args.with_integrated:
                    orders = list(permutations(meta["projects"]))
                    systems = orders[idx % len(orders)]
                    shift = rep % len(systems)
                    systems = systems[shift:] + systems[:shift]
                for system in systems:
                    requests.clear()
                    start = time.perf_counter()
                    try:
                        r = (
                            run_sus(case["question"], agent)
                            if system == "sus"
                            else run_health(
                                case["question"],
                                replace(cfg, chat_engine="sus" if system == "integrated" else "legacy"),
                                context,
                                integrated=system == "integrated",
                            )
                        )
                    # Record an adapter failure and continue with the paired case.
                    except Exception as exc:  # noqa: BLE001
                        r = {
                            "status": "failed",
                            "error": str(exc)[:500],
                            "rows": [],
                            "answer": "",
                            "chart": None,
                        }
                    elapsed = time.perf_counter() - start
                    expected = gold[case["id"]]
                    passed = (
                        r["status"] == "answered"
                        and not r.get("truncated")
                        and same_rows(
                            r["rows"],
                            expected,
                            case.get("decimals"),
                            case.get("ordered", False),
                        )
                    )
                    chart_ok = None
                    if case.get("chart"):
                        chart = r.get("chart") or {}
                        chart_ok = chart.get("type") in case.get(
                            "chart_types", ["line", "linha"]
                        ) and chart.get("points") == [list(row) for row in expected]
                    rec = dict(
                        **r,
                        project=system,
                        case=case["id"],
                        rep=rep + 1,
                        sql_ok=passed,
                        chart_ok=chart_ok,
                        latency_s=round(elapsed, 3),
                        requests=list(requests),
                    )
                    out.write(dump(rec) + "\n")
                    out.flush()
                    print(
                        rep + 1,
                        case["id"],
                        system,
                        r["status"],
                        passed,
                        len(requests),
                        round(elapsed, 1),
                        str(r.get("error", ""))[:110],
                        flush=True,
                    )
    agent.db.close()


if __name__ == "__main__":
    main()
