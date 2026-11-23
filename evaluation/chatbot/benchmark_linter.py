from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from evaluation.chatbot.evaluate_extraction_accuracy import load_dataset
from health_system_chatbot.models import GroundTruthItem
from health_system_chatbot.question_contract import build_question_contract


@dataclass(frozen=True)
class BenchmarkIssue:
    item_id: str
    code: str
    detail: str


def lint_benchmark_item(item: GroundTruthItem) -> list[BenchmarkIssue]:
    contract = build_question_contract(item.question_pt)
    sql = item.sql.upper()
    issues: list[BenchmarkIssue] = []

    limit = re.search(r"\bLIMIT\s+(\d+)\b", sql)
    if limit and contract.ranking.n is None:
        issues.append(BenchmarkIssue(item.id, "hidden_limit", limit.group(1)))

    partitioned_rank = bool(
        re.search(
            r"\b(?:ROW_NUMBER|RANK|DENSE_RANK)\s*\([^)]*\)\s*OVER\s*\([^)]*PARTITION\s+BY",
            sql,
            re.S,
        )
    )
    if partitioned_rank and not contract.ranking.partition_by:
        issues.append(BenchmarkIssue(item.id, "hidden_partition", "PARTITION BY"))

    having_support = re.search(r"\bHAVING\s+COUNT\s*\([^)]*\)\s*(?:>|>=)\s*(\d+)", sql)
    # COUNT > 0 is normally an existence/non-empty guard, not a material
    # minimum-support policy.
    if (
        having_support
        and int(having_support.group(1)) > 0
        and contract.ranking.minimum_support is None
    ):
        issues.append(
            BenchmarkIssue(item.id, "hidden_minimum_support", having_support.group(1))
        )

    question_year_values = [
        int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", item.question_pt)
    ]
    question_years = {str(year) for year in question_year_values}
    # A stated inclusive range authorizes its intermediate years too.
    if len(question_year_values) >= 2 and re.search(
        r"\b(?:19|20)\d{2}\s+(?:a|ate|entre\s+.*?e)\s+(?:19|20)\d{2}\b",
        item.question_pt.lower().replace("é", "e").replace("té", "te"),
    ):
        question_years.update(
            str(year)
            for year in range(min(question_year_values), max(question_year_values) + 1)
        )
    sql_years = set(re.findall(r"\b(?:19|20)\d{2}\b", item.sql))
    hidden_years = sorted(sql_years - question_years)
    if hidden_years:
        issues.append(
            BenchmarkIssue(item.id, "hidden_time_window", ",".join(hidden_years))
        )

    if contract.time.basis == "unresolved" and ("DT_INTER" in sql or "DT_SAIDA" in sql):
        issues.append(BenchmarkIssue(item.id, "unresolved_date_basis", "SQL selects date basis"))

    return issues


def lint_dataset(items: list[GroundTruthItem]) -> list[BenchmarkIssue]:
    return [issue for item in items for issue in lint_benchmark_item(item)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Find hidden benchmark requirements.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--fail-on-scored", action="store_true")
    args = parser.parse_args()
    items = load_dataset(args.dataset)
    by_id = {item.id: item for item in items}
    issues = lint_dataset(items)
    print(
        json.dumps(
            [issue.__dict__ for issue in issues],
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.fail_on_scored and any(
        by_id[issue.item_id].benchmark_status == "scored" for issue in issues
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
