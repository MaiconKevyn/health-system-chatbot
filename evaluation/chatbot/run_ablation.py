#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT
SRC = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evaluation.chatbot.ablation.runner import AblationRunOptions, run_ablation
from evaluation.chatbot.ablation.variants import parse_variant_names
from evaluation.chatbot.eval_core.dataset import load_dataset, select_items
from health_system_chatbot.artifacts import load_stage1_context
from health_system_chatbot.config import load_config


DEFAULT_DATASET = "evaluation/ground_truth/stage1_questions_v2.jsonl"
DEFAULT_RESULTS_ROOT = "evaluation/chatbot/results"
DEFAULT_SUITE_FILE = "evaluation/chatbot/ablation_suites.json"


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


def build_run_id(explicit: str | None) -> str:
    raw = explicit or f"ablation_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in raw.strip()).strip("._-")
    if not safe:
        raise ValueError("--run-id cannot be empty.")
    return safe


def git_sha(project_root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def load_suite(project_root: Path, suite_name: str, suite_file: str) -> dict[str, Any]:
    path = project_root / suite_file
    if not path.exists():
        raise FileNotFoundError(f"Suite file not found: {path}")
    suites = json.loads(path.read_text(encoding="utf-8"))
    try:
        suite = suites[suite_name]
    except KeyError as exc:
        choices = ", ".join(sorted(suites))
        raise ValueError(f"Unknown suite: {suite_name}. Available suites: {choices}") from exc
    if not isinstance(suite, dict):
        raise ValueError(f"Suite must be an object: {suite_name}")
    return suite


def apply_suite_args(args: argparse.Namespace, project_root: Path) -> argparse.Namespace:
    if not args.suite:
        return args
    suite = load_suite(project_root, args.suite, args.suite_file)
    if not args.dataset and suite.get("dataset"):
        args.dataset = suite["dataset"]
    if not args.ids and suite.get("ids"):
        args.ids = ",".join(suite["ids"])
    if args.limit is None and suite.get("limit") is not None:
        args.limit = int(suite["limit"])
    if not args.variants and suite.get("variants"):
        args.variants = ",".join(suite["variants"])
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run chatbot ablations and OpenAI baselines.")
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--suite", default=None)
    parser.add_argument("--suite-file", default=DEFAULT_SUITE_FILE)
    parser.add_argument("--variants", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--results-root", default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", default=None)
    parser.add_argument("--max-rows", type=int, default=10000)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--numeric-tolerance", type=float, default=1e-6)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--no-openai-baselines", action="store_true")
    parser.add_argument("--cache-openai", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(PROJECT_ROOT)
    args = apply_suite_args(args, config.project_root)
    dataset_arg = args.dataset or DEFAULT_DATASET
    variant_names = parse_variant_names(
        args.variants,
        no_openai_baselines=args.no_openai_baselines,
    )
    if args.max_workers != 1:
        raise ValueError("--max-workers is reserved for future parallel execution; use 1 for now.")

    run_id = build_run_id(args.run_id)
    run_dir = config.project_root / args.results_root / run_id
    if run_dir.exists():
        if not args.overwrite:
            raise FileExistsError(f"Run directory already exists: {run_dir}. Use --overwrite.")
        shutil.rmtree(run_dir)

    dataset_path = config.project_root / dataset_arg
    items = select_items(load_dataset(dataset_path), ids=args.ids, limit=args.limit)
    stage1_context = load_stage1_context(config.project_root, db_path=config.db_path)
    run_config = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": git_sha(config.project_root),
        "dataset": str(dataset_path),
        "suite": args.suite,
        "variants": variant_names,
        "ids": [item.id for item in items],
        "limit": args.limit,
        "db_path": str(config.db_path),
        "model": config.llm_model,
        "max_rows": args.max_rows,
        "timeout_seconds": args.timeout_seconds,
        "numeric_tolerance": args.numeric_tolerance,
        "cache_openai": args.cache_openai,
    }
    summary = run_ablation(
        config=config,
        stage1_context=stage1_context,
        items=items,
        options=AblationRunOptions(
            run_id=run_id,
            run_dir=run_dir,
            run_config=run_config,
            variant_names=variant_names,
            max_rows=args.max_rows,
            timeout_seconds=args.timeout_seconds,
            numeric_tolerance=args.numeric_tolerance,
            cache_openai=args.cache_openai,
            fail_fast=args.fail_fast,
        ),
        progress=None if args.quiet else print,
    )
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "summary": summary["variant_ranking"],
            },
            indent=2,
            ensure_ascii=True,
            default=_json_default,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
