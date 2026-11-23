"""Neutral scorer for the A x B benchmark.

    python evaluation/benchmark_ab/score.py <run_dir> [--no-judge] [--judge-model gpt-6-luna]

Inputs : <run_dir>/pred_<SYSTEM>.jsonl (A, P, B ...), evaluation/benchmark_ab/gt_sihrd9.jsonl
Outputs: <run_dir>/scored.jsonl, <run_dir>/summary.json

Execution accuracy (EX)
  The final SQL of each system is re-executed on sihrd9 (read-only, 180 s, 5000
  rows) and compared with the gold result and every accepted alternative.
  * column names and order are ignored; extra predicted columns are allowed;
  * every gold column in `compare_columns` (default: all) must map to a
    predicted column, and the row multisets must be equal (row order ignored);
  * numbers: integers exact; decimals equal up to the coarser rounding of the
    two values (at least 1 decimal place); rate/percent columns also accept x100;
  * strings: case, accents and punctuation ignored.
  EX strict  = the above.  EX numeric = only numeric gold columns are required
  (string/label columns ignored) - separates "wrong numbers" from "label wording".

Natural-language answer (NL)
  A blind LLM judge sees the question, the reference result (gold + accepted
  alternatives), the answer text and the system's own executed result, and
  returns: verdict (correct | partially_correct | incorrect) and whether the
  text is faithful to the system's own result. Unanswerable items are judged
  on whether the answer declines / flags the limitation instead of reporting a
  misleading number.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
GT = HERE / "gt_sihrd9.jsonl"
DB = "/Users/maiconkevyn/PycharmProjects/databases/sihrd9.duckdb"
PRED_ROW_CAP = 5000
SQL_TIMEOUT_S = 180
RATE_COL = re.compile(r"taxa|pct|percent|propor|razao|rate|share|perc", re.I)

# --------------------------------------------------------------------------- execution


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.decode(errors="replace")
    return v


def execute(con: duckdb.DuckDBPyConnection, sql: str) -> dict:
    sql = (sql or "").strip().rstrip(";")
    if not sql:
        return {"ok": False, "error": "no SQL"}
    cur = con.cursor()
    timer = threading.Timer(SQL_TIMEOUT_S, cur.interrupt)
    timer.start()
    t = time.time()
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(PRED_ROW_CAP + 1)
        return {"ok": True, "columns": cols, "rows": [[_jsonable(v) for v in r] for r in rows[:PRED_ROW_CAP]],
                "row_count": len(rows), "truncated": len(rows) > PRED_ROW_CAP, "seconds": round(time.time() - t, 2)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc).splitlines()[0][:300], "seconds": round(time.time() - t, 2)}
    finally:
        timer.cancel()


# --------------------------------------------------------------------------- comparison

_NUMERIC_STR = re.compile(r"^-?\d+(\.\d+)?$")


def norm(v):
    """('n', float, decimals) | ('s', str) | ('null',)."""
    if v is None:
        return ("null",)
    if isinstance(v, bool):
        return ("n", float(v), 0)
    if isinstance(v, int):
        return ("n", float(v), 0)
    if isinstance(v, float):
        if math.isnan(v):
            return ("null",)
        return ("n", v, _decimals(v))
    s = str(v).strip()
    if _NUMERIC_STR.match(s):
        return ("n", float(s), len(s.split(".")[1]) if "." in s else 0)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return ("s", s)


def _decimals(x: float) -> int:
    if float(x).is_integer():
        return 0
    r = repr(x)
    if "e" in r:
        return 6
    return min(len(r.split(".")[1].rstrip("0")), 6) if "." in r else 0


def num_eq(a: tuple, b: tuple, scale_ok: bool) -> bool:
    _, va, da = a
    _, vb, db = b
    candidates = [vb] + ([vb * 100, vb / 100] if scale_ok else [])
    for target in candidates:
        if da == 0 and db == 0 and target == vb:
            if va == vb:
                return True
            continue
        d = min(da, db)
        if not (va.is_integer() and target.is_integer()):
            d = max(d, 1)
        tol = 0.5 * 10 ** (-d) + 1e-9
        if target != vb:  # scaled: compare at the gold column's precision
            tol = max(tol, 0.5 * 10 ** (-max(min(da, 2), 1)) + 1e-9)
        if abs(va - target) <= tol:
            return True
    return False


def cell_eq(p, g, scale_ok: bool) -> bool:
    if p[0] != g[0]:
        return False
    if p[0] == "null":
        return True
    if p[0] == "s":
        return p[1] == g[1]
    return num_eq(p, g, scale_ok)


def _rows_match(gold_rows, pred_rows, gold_idx, pred_idx, scale_flags) -> bool:
    if len(gold_rows) != len(pred_rows):
        return False
    remaining = list(range(len(pred_rows)))
    for gr in gold_rows:
        hit = None
        for k in remaining:
            pr = pred_rows[k]
            if all(cell_eq(pr[pi], gr[gi], sf) for gi, pi, sf in zip(gold_idx, pred_idx, scale_flags)):
                hit = k
                break
        if hit is None:
            return False
        remaining.remove(hit)
    return True


def _column_values_match(gvals, pvals, scale_ok) -> bool:
    """Cheap necessary condition: multiset equality of one column."""
    if len(gvals) != len(pvals):
        return False
    rem = list(pvals)
    for g in gvals:
        for k, p in enumerate(rem):
            if cell_eq(p, g, scale_ok):
                rem.pop(k)
                break
        else:
            return False
    return True


def compare(gold: dict, pred: dict, compare_columns: list[str] | None, numeric_only: bool = False) -> bool:
    if not gold.get("ok") or not pred.get("ok"):
        return False
    if pred.get("truncated"):
        return False
    gcols = gold["columns"]
    wanted = [c for c in (compare_columns or gcols) if c in gcols] or gcols
    gidx_all = [gcols.index(c) for c in wanted]
    grows = [[norm(v) for v in r] for r in gold["rows"]]
    prows = [[norm(v) for v in r] for r in pred["rows"]]
    if len(grows) != len(prows):
        return False
    if not grows:
        return True
    gidx = gidx_all
    if numeric_only:
        gidx = [i for i in gidx_all if any(r[i][0] == "n" for r in grows)]
        if not gidx:
            gidx = gidx_all
    scale = [bool(RATE_COL.search(gcols[i])) for i in gidx]
    npc = len(pred["columns"])
    candidates = []
    for gi, sf in zip(gidx, scale):
        gvals = [r[gi] for r in grows]
        cands = [pi for pi in range(npc) if _column_values_match(gvals, [r[pi] for r in prows], sf)]
        if not cands:
            return False
        candidates.append(cands)

    def backtrack(k, used, chosen):
        if k == len(gidx):
            return _rows_match(grows, prows, gidx, chosen, scale)
        for pi in candidates[k]:
            if pi in used:
                continue
            if backtrack(k + 1, used | {pi}, chosen + [pi]):
                return True
        return False

    return backtrack(0, frozenset(), [])


def ex_scores(item: dict, pred_res: dict) -> dict:
    golds = [item["gold_result"]] + [a for a in item.get("alternative_results", []) if a.get("ok")]
    strict = next((k for k, g in enumerate(golds) if compare(g, pred_res, item.get("compare_columns"))), None)
    numeric = next((k for k, g in enumerate(golds)
                    if compare(g, pred_res, item.get("compare_columns"), numeric_only=True)), None)
    return {"ex_strict": strict is not None, "ex_numeric": numeric is not None,
            "matched": None if strict is None else ("gold" if strict == 0 else f"alt{strict}")}


# --------------------------------------------------------------------------- NL judge

JUDGE_SYSTEM = """You are a strict, impartial evaluator of a Portuguese health-data chatbot.
You compare the chatbot's FINAL ANSWER TEXT with a REFERENCE result computed by a
verified SQL query on the same database. You never see which system produced the answer.

Rules:
- Judge factual alignment only: the entities, numbers and conclusions the answer states.
- Accept formatting differences (1.234.567 vs 1234567, 4,31% vs 4.31%), rounding to the
  precision shown, percentages vs fractions, and synonyms/abbreviations of labels.
- If several reference results are given, an answer aligned with ANY of them is aligned
  (they are accepted interpretations of an ambiguous question).
- When the reference has MORE than 10 rows, the interface shows the full table next to the
  text, so the text may summarize: judge only the values it states; it is "correct" if every
  stated value/entity is right and the summary is not misleading.
- When the reference has 10 rows or fewer, omitting items the question explicitly asked for
  (e.g. asked for top 10, gave 3) is at most partially_correct.
- When the reference result is zero or empty, an answer that says there are no records for
  that filter/period (or that the period is outside the database coverage) is correct.
- A correct value with a wrong label/entity (e.g. right count attributed to the wrong
  specialty or hospital) is incorrect for that item.
- Extra caveats are fine. A refusal or "could not answer" for an answerable question is incorrect.
- verdict: "correct" = everything the question asks is present and matches; "partially_correct"
  = some requested values match but others are missing or wrong; "incorrect" = the main
  requested value(s) are wrong or absent.
- faithful: does the answer text agree with the chatbot's OWN executed SQL and result shown
  below? Filters/periods stated in the text may come from the SQL. "yes", "no" (text
  contradicts or invents values not supported by its own SQL/result), or "unclear" (no own
  result available).
Return only the JSON object."""

JUDGE_SYSTEM_UNANSWERABLE = """You are a strict, impartial evaluator of a Portuguese health-data chatbot.
The question below CANNOT be answered reliably with this database; the expected behaviour
is described. Decide whether the chatbot's FINAL ANSWER TEXT handled it correctly.
- "correct": it declines, or clearly explains the data limitation, and does not present a
  misleading number as the answer (it may offer a clearly-labelled alternative).
- "partially_correct": it gives the misleading number but also clearly warns that the field
  is unreliable/unsuitable.
- "incorrect": it presents the misleading number or invented data as a valid answer.
faithful: "unclear" unless the text contradicts its own executed result.
Return only the JSON object."""

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "faithful", "reason"],
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "partially_correct", "incorrect"]},
        "faithful": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "reason": {"type": "string"},
    },
}


def _table(res: dict | None, limit: int) -> str:
    if not res or not res.get("ok"):
        return "(no result)" if not res else f"(execution error: {res.get('error')})"
    rows = res["rows"][:limit]
    lines = [" | ".join(res["columns"])] + [" | ".join("" if v is None else str(v) for v in r) for r in rows]
    more = res["row_count"] - len(rows)
    if more > 0:
        lines.append(f"... (+{more} more rows; total {res['row_count']})")
    return "\n".join(lines)


def judge(client, model: str, item: dict, pred: dict, pred_res: dict | None) -> dict:
    if item["answerable"]:
        refs = [item["gold_result"]] + [a for a in item.get("alternative_results", []) if a.get("ok")]
        seen, blocks = set(), []
        for k, r in enumerate(refs):
            key = json.dumps(r.get("rows", [])[:50], default=str)
            if key in seen:
                continue
            seen.add(key)
            blocks.append(f"[reference {len(blocks) + 1}]\n{_table(r, 40 if k == 0 else 20)}")
        user = (
            f"QUESTION:\n{item['question']}\n\nREFERENCE RESULT(S):\n" + "\n\n".join(blocks)
            + (f"\n\nThe answer must also mention: {item['must_mention']}" if item.get("must_mention") else "")
            + f"\n\nCHATBOT ANSWER TEXT:\n{pred.get('answer') or '(empty)'}"
            + "\n\nCHATBOT'S OWN SQL AND EXECUTED RESULT (for the faithfulness field only):\n"
            + f"{(pred.get('sql') or '(no SQL)')[:3000]}\n---\n{_table(pred_res, 40)}"
        )
        system = JUDGE_SYSTEM
    else:
        user = (
            f"QUESTION:\n{item['question']}\n\nEXPECTED BEHAVIOUR:\n{item.get('tests') or 'Decline: the database cannot answer this.'}"
            f"\n\nCHATBOT ANSWER TEXT:\n{pred.get('answer') or '(empty)'}"
            f"\n\nCHATBOT'S OWN EXECUTED RESULT:\n{_table(pred_res, 20)}"
        )
        system = JUDGE_SYSTEM_UNANSWERABLE
    for attempt in range(4):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "judgement", "strict": True, "schema": JUDGE_SCHEMA}},
                reasoning_effort="medium",
            )
            out = json.loads(resp.choices[0].message.content)
            usage = getattr(resp, "usage", None)
            out["judge_tokens"] = {"in": getattr(usage, "prompt_tokens", None), "out": getattr(usage, "completion_tokens", None)}
            return out
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            time.sleep(2 * (attempt + 1))
    return {"verdict": None, "faithful": None, "reason": f"judge error: {err}"}


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--judge-model", default="gpt-6-luna")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    run = Path(args.run_dir)

    gt = {json.loads(l)["id"]: json.loads(l) for l in GT.open(encoding="utf-8")}
    preds = []
    for p in sorted(run.glob("pred_*.jsonl")):
        preds += [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    preds = [p for p in preds if p["id"] in gt]

    con = duckdb.connect(DB, read_only=True)
    con.execute("PRAGMA threads=8")

    client = None
    if not args.no_judge:
        import os

        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv(HERE.parent.parent / ".env")
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    cache_path = run / "scored.jsonl"
    cache = {}
    if cache_path.exists():
        for l in cache_path.open(encoding="utf-8"):
            r = json.loads(l)
            cache[(r["system"], r["id"])] = r

    def score_one(p):
        item = gt[p["id"]]
        prev = cache.get((p["system"], p["id"]))
        if prev and prev.get("answer") == p.get("answer") and prev.get("sql") == p.get("sql") \
                and (args.no_judge or prev.get("nl_verdict")):
            pred_res = prev.get("pred_result")
            rec = prev
        else:
            pred_res = execute(con, p.get("sql")) if p.get("sql") else None
            rec = {**p, "pred_result": pred_res}
        if item["answerable"]:
            rec.update(ex_scores(item, pred_res or {"ok": False}))
        else:
            rec.update(ex_strict=None, ex_numeric=None, matched=None)
        rec.update(category=item.get("category"), difficulty=item.get("difficulty"),
                   answerable=item["answerable"], decision=item.get("decision"))
        if client is not None and not rec.get("nl_verdict"):
            j = judge(client, args.judge_model, item, p, pred_res)
            rec.update(nl_verdict=j.get("verdict"), nl_faithful=j.get("faithful"),
                       nl_reason=j.get("reason"), judge_tokens=j.get("judge_tokens"))
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        scored = list(ex.map(score_one, preds))

    with cache_path.open("w", encoding="utf-8") as fh:
        for r in scored:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    summary = summarize(scored, gt)
    (run / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary["overall"], indent=2, ensure_ascii=False))
    return 0


def _rate(xs):
    xs = [x for x in xs if x is not None]
    return round(100.0 * sum(xs) / len(xs), 1) if xs else None


def summarize(scored: list[dict], gt: dict) -> dict:
    out = {"overall": {}, "by_difficulty": {}, "by_category": {}, "n_items": len(gt)}
    for system in sorted({r["system"] for r in scored}):
        rs = [r for r in scored if r["system"] == system]
        ans = [r for r in rs if r["answerable"]]
        una = [r for r in rs if not r["answerable"]]
        nl = [r for r in rs if r.get("nl_verdict")]
        out["overall"][system] = {
            "n": len(rs),
            "ex_strict": _rate([r["ex_strict"] for r in ans]),
            "ex_numeric": _rate([r["ex_numeric"] for r in ans]),
            "nl_correct": _rate([r["nl_verdict"] == "correct" for r in nl if r["answerable"]]),
            "nl_correct_or_partial": _rate([r["nl_verdict"] in ("correct", "partially_correct") for r in nl if r["answerable"]]),
            "unanswerable_handled": _rate([r["nl_verdict"] == "correct" for r in una if r.get("nl_verdict")]),
            "faithful_to_own_result": _rate([r["nl_faithful"] == "yes" for r in nl
                                             if r["answerable"] and r.get("nl_faithful") in ("yes", "no")]),
            "errors_or_no_sql": sum(1 for r in ans if not r.get("sql")),
            "latency_p50_s": _pct([r.get("latency_s") for r in rs], 50),
            "latency_p90_s": _pct([r.get("latency_s") for r in rs], 90),
        }
        for key, field in (("by_difficulty", "difficulty"), ("by_category", "category")):
            groups = {}
            for r in ans:
                groups.setdefault(str(r.get(field)), []).append(r)
            out[key].setdefault(system, {})
            for g, rr in sorted(groups.items()):
                out[key][system][g] = {
                    "n": len(rr),
                    "ex_strict": _rate([r["ex_strict"] for r in rr]),
                    "nl_correct": _rate([r.get("nl_verdict") == "correct" for r in rr if r.get("nl_verdict")]),
                }
    return out


def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = min(len(xs) - 1, max(0, int(round(q / 100 * (len(xs) - 1)))))
    return xs[k]


if __name__ == "__main__":
    raise SystemExit(main())
