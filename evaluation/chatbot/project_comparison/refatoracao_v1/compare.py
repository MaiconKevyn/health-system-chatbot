"""Review masked Portuguese answers and compare three paired SIHRD9 engines."""

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from itertools import combinations, product
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "curadoria_v1"
sys.path.insert(0, str(BASE))
from analyze import STATES, read_json, replay, write_json

ARMS = ("integrated", "sus", "health")
REPS = (1, 2)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def inputs(complete):
    cases = {c["id"]: c for c in read_json(BASE / "cases.json")}
    case_hash = hashlib.sha256((BASE / "cases.json").read_bytes()).hexdigest()
    baseline = read_json(BASE / "rodada1/manifest.json")
    gold = read_json(BASE / "rodada1/gold.json")
    records = {}
    for rep in REPS:
        folder = HERE / f"rodada{rep}"
        manifest = read_json(folder / "manifest.json")
        for key in (
            "model",
            "reasoning",
            "database",
            "database_bytes",
            "database_mtime_ns",
            "cases_sha256",
        ):
            assert manifest[key] == baseline[key], key
        assert manifest["first_rep"] == rep and manifest["cases_sha256"] == case_hash
        assert read_json(folder / "gold.json") == gold
        for line in (folder / "results.jsonl").read_text().splitlines():
            r = json.loads(line)
            key = (r["case"], r["project"], r["rep"])
            assert key not in records and key[-1] == rep
            assert all(
                q["model"] == baseline["model"] and q["effort"] == "low"
                for q in r["requests"]
            )
            r["review_id"] = digest(f"SIHRD9-refatoracao-v1:{key}")[:12]
            records[key] = r
    if complete:
        assert set(records) == set(product(cases, ARMS, REPS))
    return cases, gold, baseline, records


def checked_reviews(cases, gold, records):
    # Identical text for the same case inherits the same adjudication.
    lookup = {}
    for path, source in [
        (BASE / "nl_reviews.json", "curadoria_v1"),
        (HERE / "adjudications.json", "revisao_atual"),
    ]:
        for item in read_json(path) if path.exists() else []:
            key = (item["case"], item["answer_sha256"])
            assert key not in lookup or lookup[key]["grade"] == item["grade"]
            lookup.setdefault(
                key,
                {"grade": item["grade"], "reason": item["reason"], "source": source},
            )
    sheet = []
    reviews = []
    pending = {}
    for r in sorted(records.values(), key=lambda x: (x["case"], x["review_id"])):
        c = cases[r["case"]]
        key = (r["case"], digest(r["answer"]))
        entry = {
            "case": r["case"],
            "review_id": r["review_id"],
            "question": c["question"],
            "rubric": c["rubric"],
            "reference": gold[r["case"]],
            "answer": r["answer"],
        }
        sheet.append(entry)
        if key in lookup:
            reviews.append(
                dict(
                    case=r["case"],
                    review_id=r["review_id"],
                    answer_sha256=key[1],
                    **lookup[key],
                )
            )
        else:
            pending.setdefault(key, entry)
    return sheet, reviews, list(pending.values())


def review(mode, cases, gold, records):
    sheet, reviews, pending = checked_reviews(cases, gold, records)
    if mode == "pending":
        for r in pending:
            print(r["case"], r["review_id"], r["answer"] or "(vazio)")
    elif mode == "grade":
        by_id = {r["review_id"]: r for r in sheet}
        path = HERE / "adjudications.json"
        decisions = read_json(path) if path.exists() else []
        existing = {(d["case"], d["answer_sha256"]) for d in decisions}
        for line in sys.stdin:
            if not line.strip():
                continue
            ids, grade, reason = line.strip().split("|")
            assert grade in STATES and reason
            for ident in ids.split():
                r = by_id[ident]
                key = (r["case"], digest(r["answer"]))
                assert key not in existing
                decisions.append(
                    {
                        "case": key[0],
                        "answer_sha256": key[1],
                        "grade": grade,
                        "reason": reason,
                    }
                )
                existing.add(key)
        write_json(
            path, sorted(decisions, key=lambda x: (x["case"], x["answer_sha256"]))
        )
    else:
        assert not pending, f"{len(pending)} textos aguardam revisão"
        write_json(HERE / "blind_sheet.json", sheet)
        write_json(HERE / "nl_reviews.json", reviews)


def replay_all(cases, gold, manifest, records):
    out = {}
    for arm in ARMS:
        with duckdb.connect(
            manifest["database"],
            read_only=True,
            config={"enable_external_access": "false"},
        ) as conn:
            if arm == "sus":
                conn.execute(
                    "CREATE TEMP VIEW internacoes AS SELECT * FROM main.internacao"
                )
            for (case, project, _), r in records.items():
                if project == arm:
                    out[r["review_id"]] = replay(conn, cases[case], gold[case], r)
    write_json(HERE / "executions.json", out)


def write_csv(name, rows):
    with (HERE / name).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def paired(cases, scores, arm, control, metric):
    groups = defaultdict(list)
    wins = losses = 0
    for case, c in cases.items():
        delta = [
            int(scores[case, arm, rep][metric])
            - int(scores[case, control, rep][metric])
            for rep in REPS
        ]
        wins += delta.count(1)
        losses += delta.count(-1)
        groups[c["stratum"]].append(sum(delta) / len(REPS))
    rng = random.Random(20261123)
    boot = sorted(
        100 * sum(sum(rng.choices(g, k=len(g))) for g in groups.values()) / len(cases)
        for _ in range(20000)
    )
    n = len(cases) * len(REPS)
    return {
        "delta_pp": 100 * (wins - losses) / n,
        "ci95_pp": [boot[499], boot[19499]],
        "wins": wins,
        "losses": losses,
        "ties": n - wins - losses,
    }


def aggregate(cases, records):
    reviews = {v["review_id"]: v for v in read_json(HERE / "nl_reviews.json")}
    executions = read_json(HERE / "executions.json")
    assert set(reviews) == set(executions) == {v["review_id"] for v in records.values()}
    refs = read_json(BASE / "respostas_referencia.json")
    scores = {}
    comparison = []
    for case, rep in product(cases, REPS):
        row = {
            "caso": case,
            "rodada": rep,
            "pergunta": cases[case]["question"],
            "referencia": refs[case],
        }
        for arm in ARMS:
            key = case, arm, rep
            r = records[key]
            ident = r["review_id"]
            grade, ex = reviews[ident], executions[ident]
            assert grade["answer_sha256"] == digest(r["answer"])
            scores[key] = {
                "case": case,
                "rep": rep,
                "project": arm,
                "executable": ex["executable"],
                "ex": ex["ex"],
                "nl": grade["grade"] == "correta",
                "grade": grade["grade"],
                "calls": len(r["requests"]),
            }
            for field, value in {
                "resposta": r["answer"],
                "avaliacao_nl": grade["grade"],
                "motivo": grade["reason"],
                "sql": r.get("sql"),
                "executavel": ex["executable"],
                "ex": ex["ex"],
            }.items():
                row[f"{arm}_{field}"] = value
        comparison.append(row)
    write_csv("comparacao.csv", comparison)
    write_csv("scorecard.csv", list(scores.values()))
    totals = {}
    for arm in ARMS:
        subset = [s for s in scores.values() if s["project"] == arm]
        counts = {
            metric: sum(s[metric] for s in subset)
            for metric in ("executable", "ex", "nl", "calls")
        }
        counts["grades"] = dict(Counter(s["grade"] for s in subset))
        counts["nl_both"] = sum(
            all(scores[case, arm, r]["nl"] for r in REPS) for case in cases
        )
        counts["ex_both"] = sum(
            all(scores[case, arm, r]["ex"] for r in REPS) for case in cases
        )
        counts["strata"] = {
            g: {
                m: sum(s[m] for s in subset if cases[s["case"]]["stratum"] == g)
                for m in ("nl", "ex")
            }
            for g in sorted({c["stratum"] for c in cases.values()})
        }
        totals[arm] = counts
    summary = {
        "totals": totals,
        "review_sources": dict(Counter(r["source"] for r in reviews.values())),
        "paired": {
            f"{a}-{b}": {m: paired(cases, scores, a, b, m) for m in ("nl", "ex")}
            for a, b in combinations(ARMS, 2)
        },
    }
    write_json(HERE / "summary.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("pending", "grade", "seal", "replay", "aggregate")
    )
    mode = parser.parse_args().mode
    cases, gold, manifest, records = inputs(mode not in {"grade", "pending"})
    if mode == "replay":
        replay_all(cases, gold, manifest, records)
    elif mode == "aggregate":
        aggregate(cases, records)
    else:
        review(mode, cases, gold, records)
