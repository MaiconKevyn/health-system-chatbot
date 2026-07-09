from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .audit import default_audit_log_path, read_audit_records
from .artifacts import load_stage1_context
from .config import load_config
from .duckdb_executor import execute_validated_sql
from .evaluation import evaluate_dataset
from .schema_context import build_schema_index, retrieve_context
from .sql_generator import generate_sql_plan
from .sql_validator import validate_sql
from .workflow import run_chat


def _print_json(payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))


def _print_chat_answer(answer: Any) -> None:
    print(answer.answer_pt)
    if answer.result_summary:
        print(f"\nResumo tecnico: {answer.result_summary}")
    if answer.caveats:
        print("Caveats:")
        for caveat in answer.caveats:
            print(f"- {caveat}")
    if answer.sql:
        print("\nSQL:")
        print(answer.sql)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print structured JSON output.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="health-system-chatbot")
    sub = parser.add_subparsers(dest="command")

    config_p = sub.add_parser("config", help="Show safe configuration.")
    _add_common(config_p)

    ask_p = sub.add_parser("ask", help="Ask a natural-language question.")
    ask_p.add_argument("question")
    ask_p.add_argument("--show-sql", action="store_true")
    ask_p.add_argument("--show-debug", action="store_true")
    ask_p.add_argument("--no-llm", action="store_true", help="Debug only: disables model SQL generation.")
    _add_common(ask_p)

    ask_file_p = sub.add_parser("ask-file", help="Ask many questions from a text file.")
    ask_file_p.add_argument("questions_file")
    ask_file_p.add_argument("--show-sql", action="store_true")
    ask_file_p.add_argument("--show-debug", action="store_true")
    ask_file_p.add_argument("--no-llm", action="store_true", help="Debug only: disables model SQL generation.")
    ask_file_p.add_argument(
        "--output",
        default="evaluation/chatbot/results/ad_hoc_questions.jsonl",
        help="JSONL file for compact batch answers.",
    )
    _add_common(ask_file_p)

    audit_p = sub.add_parser("audit-log", help="Inspect the append-only chat audit log.")
    audit_p.add_argument("--limit", type=int, default=20)
    _add_common(audit_p)

    context_p = sub.add_parser("context", help="Retrieve chatbot context for a question.")
    context_p.add_argument("question")
    _add_common(context_p)

    draft_p = sub.add_parser("draft-sql", help="Draft a structured SQL plan.")
    draft_p.add_argument("question")
    draft_p.add_argument("--no-llm", action="store_true", help="Debug only: disables model SQL generation.")
    _add_common(draft_p)

    validate_p = sub.add_parser("validate-sql", help="Validate a SQL string without executing it.")
    validate_p.add_argument("sql")
    _add_common(validate_p)

    run_p = sub.add_parser("run-sql", help="Validate and execute SQL read-only.")
    run_p.add_argument("sql")
    _add_common(run_p)

    eval_p = sub.add_parser("eval", help="Evaluate against the ground truth dataset.")
    eval_p.add_argument(
        "--dataset",
        default="evaluation/ground_truth/stage1_questions_v2.jsonl",
    )
    eval_p.add_argument("--output", default="evaluation/chatbot/results/iteration_001.json")
    eval_p.add_argument("--limit", type=int, default=None)
    eval_p.add_argument("--no-llm", action="store_true", help="Debug only: disables model SQL generation.")
    _add_common(eval_p)

    index_p = sub.add_parser("index", help="Index management.")
    index_sub = index_p.add_subparsers(dest="index_command")
    index_sub.add_parser("rebuild", help="Rebuild the LlamaIndex schema index.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    config = load_config()

    if args.command == "config":
        _print_json(config.safe_summary())
        return 0

    ctx = load_stage1_context(config.project_root, db_path=config.db_path)

    if args.command == "ask":
        answer = run_chat(
            args.question,
            config=config,
            stage1_context=ctx,
            show_sql=args.show_sql,
            show_debug=args.show_debug,
            allow_llm=not args.no_llm,
        )
        if args.json:
            _print_json(answer)
        else:
            _print_chat_answer(answer)
        return 0 if answer.status in {"answered", "clarified", "refused"} else 2

    if args.command == "ask-file":
        questions_path = config.project_root / Path(args.questions_file)
        questions = [
            line.strip()
            for line in questions_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        output_path = config.project_root / Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        statuses = []
        with output_path.open("a", encoding="utf-8") as f:
            for question in questions:
                answer = run_chat(
                    question,
                    config=config,
                    stage1_context=ctx,
                    show_sql=args.show_sql,
                    show_debug=args.show_debug,
                    allow_llm=not args.no_llm,
                )
                statuses.append(answer.status)
                f.write(
                    json.dumps(
                        {
                            "question": question,
                            "answer": answer.model_dump(),
                        },
                        ensure_ascii=True,
                        default=str,
                    )
                )
                f.write("\n")
                if not args.json:
                    print(f"\n## {question}\n{answer.status}")
                    _print_chat_answer(answer)
        payload = {
            "questions": len(questions),
            "output": str(output_path),
            "audit_log": str(default_audit_log_path(config)),
            "statuses": statuses,
        }
        if args.json:
            _print_json(payload)
        else:
            print("\nBatch summary:")
            print(json.dumps(payload, indent=2, ensure_ascii=True, default=str))
        return 0

    if args.command == "audit-log":
        path = default_audit_log_path(config)
        records = read_audit_records(path, limit=args.limit)
        if args.json:
            _print_json({"path": str(path), "records": records})
        else:
            print(f"Audit log: {path}")
            for record in records:
                print(
                    f"{record.get('logged_at')} | "
                    f"{record.get('answer_status')} | "
                    f"{record.get('question')}"
                )
        return 0

    if args.command == "context":
        retrieved = retrieve_context(args.question, ctx, config=config)
        if args.json:
            _print_json(retrieved)
        else:
            print("Tables:", ", ".join(retrieved.tables))
            print("Retrieval mode:", retrieved.retrieval_mode)
            print("Caveats:")
            for caveat in retrieved.data_quality_caveats:
                print(f"- {caveat}")
        return 0

    if args.command == "draft-sql":
        retrieved = retrieve_context(args.question, ctx, config=config)
        plan = generate_sql_plan(
            args.question,
            retrieved,
            ctx,
            config,
            allow_llm=not args.no_llm,
        )
        if args.json:
            _print_json(plan)
        else:
            print(plan.sql)
        return 0

    if args.command == "validate-sql":
        result = validate_sql(args.sql, ctx)
        if args.json:
            _print_json(result)
        else:
            print("valid" if result.is_valid else "invalid")
            for error in result.errors:
                print(f"ERROR: {error}")
            for warning in result.warnings:
                print(f"WARNING: {warning}")
        return 0 if result.is_valid else 2

    if args.command == "run-sql":
        validation = validate_sql(args.sql, ctx)
        if not validation.is_valid:
            _print_json(validation) if args.json else print("; ".join(validation.errors))
            return 2
        execution = execute_validated_sql(validation, db_path=config.db_path, max_rows=config.max_rows)
        if args.json:
            _print_json(execution)
        else:
            print(json.dumps(execution.rows, indent=2, ensure_ascii=True, default=str))
        return 0

    if args.command == "eval":
        payload = evaluate_dataset(
            dataset=config.project_root / Path(args.dataset),
            output=config.project_root / Path(args.output),
            limit=args.limit,
            allow_llm=not args.no_llm,
            config=config,
        )
        if args.json:
            _print_json(payload)
        else:
            print(json.dumps(payload["summary"], indent=2, ensure_ascii=True, default=str))
        return 0

    if args.command == "index":
        if args.index_command == "rebuild":
            path = build_schema_index(ctx, config)
            print(path)
            return 0
        parser.error("index requires a subcommand")

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
