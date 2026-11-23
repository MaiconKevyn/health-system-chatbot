"""Check historical sources against the physical SIHRD9 and the deployed examples."""

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import duckdb
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
LEGACY = ROOT / "evaluation/ground_truth"
SUS = ROOT.parent / "text-to-sql-chatbot"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def normalize(text):
    plain = unicodedata.normalize("NFKD", text.casefold())
    return " ".join(
        re.findall(
            r"[a-z0-9]+", "".join(c for c in plain if not unicodedata.combining(c))
        )
    )


def digest(paths, root):
    result = hashlib.sha256()
    for path in sorted(set(paths)):
        result.update(str(path.relative_to(root)).encode() + b"\0")
        result.update(hashlib.sha256(path.read_bytes()).digest())
    return result.hexdigest()


def main():
    cases = json.loads((HERE / "cases.json").read_text())
    manifest = json.loads((HERE / "rodada1/manifest.json").read_text())
    sets = {p.stem: read_jsonl(p) for p in LEGACY.glob("*.jsonl")}
    sets["questions_sihrd9"] = json.loads(
        (ROOT / "evaluation/chatbot/model_comparison/questions_sihrd9.json").read_text()
    )
    contracts = json.loads((LEGACY / "benchmark_contracts.json").read_text())
    examples = [
        r["question_pt"] for r in read_jsonl(ROOT / "docs/query_examples_bank.jsonl")
    ]
    sus_doc = yaml.safe_load((SUS / "knowledge/sihrd9.yaml").read_text())
    examples += [r["question"] for r in sus_doc["examples"]]
    benchmark_questions = {normalize(r["question"]) for r in cases}
    sources = {r["id"]: r for group in sets.values() for r in group}
    assert all(c["source_id"] in sources for c in cases)
    report = {
        "physical_database": manifest["database"],
        "sources": {},
        "curated_sources": {},
        "runtime_examples_checked": len(examples),
        "exact_example_matches": sorted(
            benchmark_questions & set(map(normalize, examples))
        ),
    }
    with duckdb.connect(manifest["database"], read_only=True) as con:
        for source, group in sorted(sets.items()):
            failed = []
            for r in group:
                try:
                    con.execute("EXPLAIN " + r["sql"])
                except duckdb.Error:
                    failed.append(r["id"])
            report["sources"][source] = {
                "n": len(group),
                "bind_on_native_sihrd9": len(group) - len(failed),
                "failed_ids": failed,
            }
        for case in cases:
            row = sources[case["source_id"]]
            report["curated_sources"][case["id"]] = {
                "source_id": row["id"],
                "original_question": row.get("question_pt", row.get("question")),
                "original_contract": contracts.get(row["id"], {}).get(
                    "benchmark_status"
                ),
            }
    report["strata"] = dict(Counter(c["stratum"] for c in cases))
    report["health_runtime_inputs_sha256"] = digest(
        list((ROOT / "src/health_system_chatbot").rglob("*.py"))
        + [
            p
            for p in (ROOT / "docs").rglob("*")
            if p.suffix in {".json", ".jsonl", ".csv"}
        ],
        ROOT,
    )
    report["sus_runtime_inputs_sha256"] = digest(
        list((SUS / "src").rglob("*.py")) + [SUS / "knowledge/sihrd9.yaml"], SUS
    )
    (HERE / "source_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        {k: (v["n"], v["bind_on_native_sihrd9"]) for k, v in report["sources"].items()}
    )
    print("Exemplos idênticos:", report["exact_example_matches"])


if __name__ == "__main__":
    main()
