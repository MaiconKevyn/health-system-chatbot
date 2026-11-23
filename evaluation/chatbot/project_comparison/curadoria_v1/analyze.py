"""Make a masked review sheet, replay returned SQL, and aggregate paired metrics."""

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from run import same_rows

PROJECTS = ("health", "sus")
STATES = {"correta", "parcial", "incorreta", "sem_resposta"}


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def read_run():
    cases = {c["id"]: c for c in read_json(HERE / "cases.json")}
    gold = read_json(HERE / "rodada1/gold.json")
    manifests = []
    records = []
    for rep in (1, 2):
        d = HERE / f"rodada{rep}"
        m = read_json(d / "manifest.json")
        assert gold == read_json(d / "gold.json") and m["first_rep"] == rep
        assert (
            m["cases_sha256"]
            == hashlib.sha256((HERE / "cases.json").read_bytes()).hexdigest()
        )
        manifests.append(m)
        for line in (d / "results.jsonl").read_text().splitlines():
            r = json.loads(line)
            assert r["rep"] == rep
            key = f"SIHRD9-blind-v1:{r['project']}:{r['rep']}:{r['case']}"
            r["review_id"] = hashlib.sha256(key.encode()).hexdigest()[:10]
            records.append(r)
    for field in [
        "database",
        "database_bytes",
        "database_mtime_ns",
        "model",
        "reasoning",
        "health_head",
        "sus_head",
    ]:
        assert manifests[0][field] == manifests[1][field]
    assert len({r["review_id"] for r in records}) == len(records)
    return cases, gold, manifests[0], records


def blind(cases, gold, records):
    sheet = []
    for r in sorted(records, key=lambda v: (v["case"], v["review_id"])):
        c = cases[r["case"]]
        sheet.append(
            {
                "case": r["case"],
                "review_id": r["review_id"],
                "question": c["question"],
                "rubric": c["rubric"],
                "reference": gold[r["case"]],
                "answer": r["answer"],
            }
        )
    write_json(HERE / "blind_sheet.json", sheet)


def replay(conn, case, gold, record):
    sql = record.get("sql")
    if not sql:
        return {"executable": False, "ex": False, "reason": "sem SQL final"}
    try:
        statements = conn.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            return {
                "executable": False,
                "ex": False,
                "reason": "forma de consulta inválida",
            }
        timer = threading.Timer(90, conn.interrupt)
        timer.start()
        try:
            result = conn.execute(sql)
            columns = [col[0] for col in result.description]
            values = result.fetchmany(len(gold) + 1)
        finally:
            timer.cancel()
            timer.join()
    except duckdb.Error as e:
        return {"executable": False, "ex": False, "reason": str(e)[:350]}
    match = same_rows(values, gold, case.get("decimals"), case.get("ordered", False))
    return {
        "executable": True,
        "ex": match,
        "columns": columns,
        "rows_preview": values,
        "reason": "equivalente" if match else "resultado diferente",
    }


def confirm_complete(cases, records):
    expected = {(c, p, r) for c in cases for p in PROJECTS for r in (1, 2)}
    assert {(r["case"], r["project"], r["rep"]) for r in records} == expected


def intervals(cases, scored):
    # Paired differences averaged across both repetitions first; resample entire
    # questions within each prespecified stratum, retaining the 8:8:8:8 mix.
    by_key = {(r["case"], r["project"], r["rep"]): r for r in scored}
    rng = random.Random(20261123)
    result = {}
    for metric in ("ex", "nl"):
        groups = defaultdict(list)
        for c in cases.values():
            diff = statistics.mean(
                int(by_key[c["id"], "sus", rep][metric])
                - int(by_key[c["id"], "health", rep][metric])
                for rep in (1, 2)
            )
            groups[c["stratum"]].append(diff)
        bootstrap = sorted(
            100
            * sum(sum(rng.choices(g, k=len(g))) for g in groups.values())
            / len(cases)
            for _ in range(20000)
        )
        result[metric] = {
            "difference_pp_sus_minus_health": 100
            * sum(map(sum, groups.values()))
            / len(cases),
            "bootstrap_95_pp": [bootstrap[499], bootstrap[19499]],
        }
    return result


def aggregate(cases, records):
    confirm_complete(cases, records)
    reviews = {r["review_id"]: r for r in read_json(HERE / "nl_reviews.json")}
    executions = read_json(HERE / "executions.json")
    ids = {r["review_id"] for r in records}
    assert ids == set(reviews) == set(executions)
    rows = []
    for r in records:
        ident = r["review_id"]
        review = reviews[ident]
        assert review["grade"] in STATES and review["reason"]
        assert (
            review["answer_sha256"] == hashlib.sha256(r["answer"].encode()).hexdigest()
        ), ident
        assert all(
            req["model"] == "gpt-6-luna" and req["effort"] == "low"
            for req in r["requests"]
        )
        rows.append(
            {
                "case": r["case"],
                "stratum": cases[r["case"]]["stratum"],
                "project": r["project"],
                "rep": r["rep"],
                "review_id": ident,
                "executable": executions[ident]["executable"],
                "ex": executions[ident]["ex"],
                "nl": review["grade"] == "correta",
                "grade": review["grade"],
                "reason": review["reason"],
                "calls": len(r["requests"]),
            }
        )
    rows.sort(key=lambda r: (r["case"], r["project"], r["rep"]))
    with (HERE / "scorecard.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    totals = {}
    for project in PROJECTS:
        group = [r for r in rows if r["project"] == project]
        metrics = {
            k: sum(r[k] for r in group) for k in ("executable", "ex", "nl", "calls")
        }
        metrics["grades"] = dict(Counter(r["grade"] for r in group))
        metrics["matrix_ex_nl"] = dict(
            Counter(f"ex{int(r['ex'])}_nl{int(r['nl'])}" for r in group)
        )
        metrics["nl_both_runs"] = sum(
            all(r["nl"] for r in group if r["case"] == c) for c in cases
        )
        metrics["nl_one_run"] = sum(
            sum(r["nl"] for r in group if r["case"] == c) == 1 for c in cases
        )
        metrics["strata"] = {
            s: {k: sum(r[k] for r in group if r["stratum"] == s) for k in ("ex", "nl")}
            for s in sorted({r["stratum"] for r in group})
        }
        totals[project] = metrics
    by_key = {(r["case"], r["rep"], r["project"]): r for r in rows}
    source = {r["review_id"]: r for r in records}
    references = read_json(HERE / "respostas_referencia.json")
    comparison = []
    for case_id, case in cases.items():
        for rep in (1, 2):
            pair = {
                "id": case_id,
                "rodada": rep,
                "pergunta": case["question"],
                "referencia": references[case_id],
            }
            for project in PROJECTS:
                score = by_key[case_id, rep, project]
                raw = source[score["review_id"]]
                for label, value in [
                    ("resposta", raw["answer"]),
                    ("avaliacao_nl", score["grade"]),
                    ("motivo", score["reason"]),
                    ("sql", raw.get("sql")),
                    ("ex", score["ex"]),
                ]:
                    pair[f"{project}_{label}"] = value
            comparison.append(pair)
    with (HERE / "comparacao.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=comparison[0].keys())
        writer.writeheader()
        writer.writerows(comparison)
    pairs = {
        k: dict(
            Counter(
                ("empate" if a[k] == b[k] else "health" if a[k] else "sus")
                for c in cases
                for rep in (1, 2)
                for a, b in [(by_key[c, rep, "health"], by_key[c, rep, "sus"])]
            )
        )
        for k in ("ex", "nl")
    }
    result = {"totals": totals, "paired": pairs, "intervals": intervals(cases, rows)}
    write_json(HERE / "summary.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["blind", "replay", "aggregate"])
    mode = parser.parse_args().mode
    cases, gold, manifest, records = read_run()
    if mode == "blind":
        blind(cases, gold, records)
    elif mode == "replay":
        confirm_complete(cases, records)
        results = {}
        with duckdb.connect(
            manifest["database"],
            read_only=True,
            config={"enable_external_access": "false"},
        ) as conn:
            for project in PROJECTS:
                if project == "sus":
                    conn.execute(
                        "CREATE TEMP VIEW internacoes AS SELECT * FROM main.internacao"
                    )
                for r in records:
                    if r["project"] == project:
                        results[r["review_id"]] = replay(
                            conn, cases[r["case"]], gold[r["case"]], r
                        )
        write_json(HERE / "executions.json", results)
    else:
        aggregate(cases, records)
