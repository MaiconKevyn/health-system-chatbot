"""Score factual claims in Portuguese against the frozen SIHRD9 pilot answers."""

import argparse
import json
import re
import statistics
from decimal import Decimal
from pathlib import Path


def number_pt(value, decimals=0):
    formatted = f"{Decimal(str(value)):,.{decimals}f}"
    integer, _, fraction = formatted.partition(".")
    grouped = r"\.?".join(integer.split(","))
    # For this pilot the prompt explicitly requests two decimal places when applicable.
    return grouped + ("," + fraction if decimals else "")


def text_ok(case, rows, answer):
    """Match the requested scalar or every labelled pair, including ranking order."""
    answer = answer.replace("*", "").casefold()
    if len(rows) == 1 and len(rows[0]) == 1:
        value = number_pt(rows[0][0], case.get("decimals", 0))
        unit = {"Q03": r"\s*dias?", "Q06": r"\s*%"}.get(case["id"], "")
        currency = r"r\$\s*" if case["id"] == "Q04" else ""
        return (
            re.search(r"(?<!\w)" + currency + value + r"(?!\d|[.,]\d)" + unit, answer)
            is not None
        )

    # Bind the year, CID or UF to its count. Accept "2018: 30.661" and
    # "30.661 em 2018", without crossing into another number or list item.
    cursor = 0
    connector = r"(?:[^\d;|\n]{0,35}?|[ \t]*\|[ \t]*)"
    for label, count in rows:
        key = re.escape(str(label).casefold())
        if case["id"] == "Q09":
            key = key[:3] + r"\.?" + key[3:]
        value = number_pt(count)
        pattern = (
            rf"(?<!\w)(?:{key}{connector}{value}|{value}{connector}{key})(?!\w|[.,]\d)"
        )
        match = re.search(pattern, answer[cursor:])
        if match is None:
            return False
        cursor += match.end()
    return True


def summarize(directory, cases_path):
    cases = {c["id"]: c for c in json.loads(cases_path.read_text())}
    gold = json.loads((directory / "gold.json").read_text())
    manifest = json.loads((directory / "manifest.json").read_text())
    records = [
        json.loads(line)
        for line in (directory / "results.jsonl").read_text().splitlines()
    ]
    keys = [(r["project"], r["case"], r["rep"]) for r in records]
    first_rep = manifest.get("first_rep", 1)
    expected = {
        (project, case, rep)
        for project in ("health", "sus")
        for case in cases
        for rep in range(first_rep, first_rep + manifest["reps"])
    }
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError("Incomplete or duplicated paired run")
    for r in records:
        case = cases[r["case"]]
        r["text_ok"] = r["status"] == "answered" and text_ok(
            case, gold[r["case"]], r["answer"]
        )
        r["delivered"] = r["text_ok"] and r["chart_ok"] is not False
        if any(
            call["model"] != manifest["model"]
            or call["effort"] != manifest["reasoning"]
            for call in r["requests"]
        ):
            raise ValueError("Inconsistent LLM request configuration")
    totals = {}
    for project in ("health", "sus"):
        group = [r for r in records if r["project"] == project]
        totals[project] = {
            "runs": len(group),
            "complete": sum(r["delivered"] for r in group),
            "text": sum(r["text_ok"] for r in group),
            "sql": sum(r["sql_ok"] for r in group),
            "charts": sum(r["chart_ok"] is True for r in group),
            "charts_requested": sum(r["chart_ok"] is not None for r in group),
            "requests": sum(len(r["requests"]) for r in group),
            "median_latency_s": round(
                statistics.median(r["latency_s"] for r in group), 3
            ),
        }
    details = [
        {
            k: r[k]
            for k in (
                "project",
                "case",
                "rep",
                "sql_ok",
                "text_ok",
                "chart_ok",
                "delivered",
            )
        }
        for r in records
    ]
    return {"totals": totals, "details": details}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--cases", type=Path, default=Path(__file__).with_name("cases.json")
    )
    args = parser.parse_args()
    summary = summarize(args.directory, args.cases)
    (args.directory / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps(summary["totals"], indent=2))
