#!/usr/bin/env python3
"""Reconcile the example-bank v2 hard-73 run and its manual failure audit."""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
RUN = Path(__file__).resolve().parents[1]
OLD_RUN = ROOT / "evaluation/chatbot/results/hard73_full_agent_gpt54nano_no_examples_20260711"


def load(path: Path):
    return json.loads(path.read_text())


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def main() -> None:
    results = load(RUN / "variants/full_agent/results.json")
    records = results["records"]
    audit = load(RUN / "audit/failure_audit.json")
    cases = audit["cases"]
    failed = [row for row in records if not row["result_match"]]

    assert len(records) == 73
    assert len(failed) == 49
    assert len(cases) == 49
    assert len({case["id"] for case in cases}) == 49
    assert {case["id"] for case in cases} == {row["id"] for row in failed}
    assert all(len(row.get("query_examples") or []) == 4 for row in records)

    categories = collections.Counter(case["category"] for case in cases)
    confidence = collections.Counter(case["confidence"] for case in cases)
    example_all = collections.Counter(ex for row in records for ex in row["query_examples"])
    example_fail = collections.Counter(ex for row in failed for ex in row["query_examples"])

    old_records = {
        row["id"]: row
        for row in load(OLD_RUN / "variants/full_agent/results.json")["records"]
    }
    new_wins = sorted(
        row["id"] for row in records
        if row["result_match"] and not old_records[row["id"]]["result_match"]
    )
    regressions = sorted(
        row["id"] for row in records
        if not row["result_match"] and old_records[row["id"]]["result_match"]
    )

    bank = [
        json.loads(line)
        for line in (ROOT / "docs/query_examples_bank.jsonl").read_text().splitlines()
        if line.strip()
    ]
    ground_truth = [
        json.loads(line)
        for line in (ROOT / "evaluation/ground_truth/ground_truth_hard_73.jsonl").read_text().splitlines()
        if line.strip()
    ]
    exact_question_overlap = []
    exact_sql_overlap = []
    for example in bank:
        for item in ground_truth:
            question = item.get("question_pt") or item.get("question") or ""
            sql = item.get("sql") or item.get("ground_truth_sql") or ""
            if normalize(example["question_pt"]) == normalize(question):
                exact_question_overlap.append([example["id"], item["id"]])
            if normalize(example["sql"]) == normalize(sql):
                exact_sql_overlap.append([example["id"], item["id"]])

    summary = {
        "records": len(records),
        "strict_matches": sum(bool(row["result_match"]) for row in records),
        "strict_failures": len(failed),
        "strict_match_rate": sum(bool(row["result_match"]) for row in records) / len(records),
        "categories": dict(sorted(categories.items())),
        "confidence": dict(sorted(confidence.items())),
        "new_wins_vs_no_examples": new_wins,
        "regressions_vs_no_examples": regressions,
        "net_match_change": len(new_wins) - len(regressions),
        "catalog_tool_calls": results["summary"]["catalog_tool_call_count"],
        "example_exposure_all": dict(sorted(example_all.items())),
        "example_exposure_failures": dict(sorted(example_fail.items())),
        "query_examples_enabled_recorded_in_config": load(RUN / "run_config.json")["query_examples_enabled"],
        "records_with_four_examples": sum(len(row.get("query_examples") or []) == 4 for row in records),
        "example_bank_size": len(bank),
        "exact_question_overlap": exact_question_overlap,
        "exact_sql_overlap": exact_sql_overlap,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
