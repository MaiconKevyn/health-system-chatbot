"""Build the curated sihrd9 ground truth for the A x B benchmark.

Pool:
  * text-to-sql-chatbot/eval/ground_truth.yaml (272 cases: 57 native + 215 from
    the shared GT228, already de-duplicated and disambiguated by that project)
  * evaluation/chatbot/model_comparison/questions_sihrd9.json (M01-M16)

Steps (all decisions recorded, nothing silent):
  1. automatic migration sihrd5 -> sihrd9 (fact table rename only);
  2. manual decisions from curation.yaml (rewrite SQL/question, drop, change
     answerability) - each with a reason;
  3. interpretation alternatives: when the question does not say which date it
     means, the gold is accepted with year(DT_INTER) or year(DT_SAIDA);
  4. every gold (and alternative) is executed on sihrd9 and its result stored;
  5. risk flags for review.

    python evaluation/benchmark_ab/build_gt.py            # writes gt_sihrd9.jsonl + curation_report.md
    python evaluation/benchmark_ab/build_gt.py --flags    # only print flags, no write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path

import duckdb
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
B_GT = ROOT.parent / "text-to-sql-chatbot" / "eval" / "ground_truth.yaml"
M_GT = ROOT / "evaluation" / "chatbot" / "model_comparison" / "questions_sihrd9.json"
DB = ROOT.parent / "databases" / "sihrd9.duckdb"
CURATION = HERE / "curation.yaml"
OUT = HERE / "gt_sihrd9.jsonl"
REPORT = HERE / "curation_report.md"
MAX_GOLD_ROWS = 300

DIFFICULTY = {"facil": "easy", "easy": "easy", "media": "medium", "medio": "medium",
              "medium": "medium", "dificil": "hard", "hard": "hard"}


# Labels of internacao.ESPEC (AIH bed-specialty domain). The `especialidade`
# table in sihrd9 uses another coding, so golds label ESPEC with this CASE.
ESPEC_LABEL = (
    "CASE i.ESPEC WHEN 1 THEN 'Cirúrgico' WHEN 2 THEN 'Obstétrico' WHEN 3 THEN 'Clínico' "
    "WHEN 4 THEN 'Crônicos' WHEN 5 THEN 'Psiquiatria' WHEN 6 THEN 'Pneumologia sanitária' "
    "WHEN 7 THEN 'Pediátrico' WHEN 8 THEN 'Reabilitação' WHEN 9 THEN 'Leito dia / cirúrgico' "
    "WHEN 10 THEN 'Leito dia / AIDS' WHEN 11 THEN 'Leito dia / fibrose cística' "
    "WHEN 12 THEN 'Leito dia / intercorrência pós-transplante' WHEN 13 THEN 'Leito dia / geriatria' "
    "WHEN 14 THEN 'Leito dia / saúde mental' WHEN 17 THEN 'Não documentado' "
    "WHEN 87 THEN 'Saúde mental (longa permanência)' END"
)


_RES_JOIN = re.compile(
    r'JOIN\s+municipios\s+(\w+)\s+ON\s+i\."?MUNIC_RES"?\s*=\s*\1\."?CO_MUNICIPIO_6D"?', re.I)
_RES_JOIN_DF = re.compile(
    r'JOIN\s+municipios\s+(\w+)\s+ON\s+\1\.CO_MUNICIPIO_6D\s*=\s*CASE WHEN i\.MUNIC_RES BETWEEN 530000 AND 539999 THEN 530010 ELSE i\.MUNIC_RES END', re.I)


def hospital_geo(sql: str) -> str:
    """Residence join -> place-of-care join (hospital.MUNIC_MOV), DF regions -> Brasília."""
    hosp = ("JOIN hospital h_geo ON i.CNES = h_geo.CNES JOIN municipios \\1 ON \\1.CO_MUNICIPIO_6D = "
            "CASE WHEN h_geo.MUNIC_MOV BETWEEN 530000 AND 539999 THEN 530010 ELSE h_geo.MUNIC_MOV END")
    out = _RES_JOIN_DF.sub(hosp, sql)
    out = _RES_JOIN.sub(hosp, out)
    if out == sql:
        raise ValueError("geo_alternative: no residence join found in gold SQL")
    return out


def migrate(sql: str) -> str:
    sql = re.sub(r"\b(FROM|JOIN)\s+internacoes\b", r"\1 internacao", sql, flags=re.I)
    sql = re.sub(r"\binternacoes\.", "internacao.", sql, flags=re.I)
    return sql.strip().rstrip(";").strip()


# Question explicitly anchors the year on admission or on discharge.
_INTER_WORDS = re.compile(r"intern(a[cç][aã]o|ad[oa]s?)\s+(iniciad|em\s+que\s+entr)|iniciad|data de (entrada|interna)|admiss|entrad", re.I)
_SAIDA_WORDS = re.compile(r"\b(alta|altas|sa[ií]da|sa[ií]ram|encerrad|competência|competencia)\b", re.I)


def date_alternative(question: str, sql: str) -> str | None:
    """Swap DT_INTER <-> DT_SAIDA when the question leaves the date open."""
    has_inter = re.search(r"\bDT_INTER\b", sql, re.I)
    has_saida = re.search(r"\bDT_SAIDA\b", sql, re.I)
    if bool(has_inter) == bool(has_saida):  # none, or both used on purpose
        return None
    if _INTER_WORDS.search(question) or _SAIDA_WORDS.search(question):
        return None
    if re.search(r"perman|dias|tempo m[eé]dio|dura[cç]", question, re.I) and has_inter and has_saida:
        return None
    swapped = re.sub(r"\bDT_INTER\b", "__TMP__", sql, flags=re.I)
    swapped = re.sub(r"\bDT_SAIDA\b", "DT_INTER", swapped, flags=re.I)
    return swapped.replace("__TMP__", "DT_SAIDA")


FLAG_PATTERNS = {
    "proc_rea_on_fact": r"\bi\.\"?PROC_REA\b|internacao\.PROC_REA|FROM\s+internacao\b(?![^;]*internacao_procedimento)[^;]*\bPROC_REA\b",
    "espec_dim_join": r"JOIN\s+especialidade\b",
    "raca_dim_inner_join": r"(?<!LEFT\s)JOIN\s+raca_cor\b",
    "old_placeholder": r"(DIAG_SECUN|CID_MORTE|CID_NOTIF)\s*(<>|!=|=)\s*'0'|(DIAG_SECUN|CID_MORTE|CID_NOTIF)\s+IS\s+(NOT\s+)?NULL",
    "uses_secun_or_morte": r"\b(DIAG_SECUN|CID_MORTE|CID_NOTIF|DIAGSEC\d)\b",
    "year_2007": r"\b2007\b",
    "tempo_join": r"JOIN\s+tempo\b",
    "string_code_literal": r"(COMPLEX|RACA_COR)\s*(=|IN\s*\()\s*'",
    "munic_inner_join": r"(?<!LEFT\s)JOIN\s+municipios\b",
    "gestrisco_or_uti_int_to": r"\b(GESTRISCO|UTI_INT_TO)\b",
    "hospital_or_socio": r"\b(hospital|socioeconomico)\b",
}


def jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def execute(con, sql: str) -> dict:
    cur = con.cursor()
    t = time.time()
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_GOLD_ROWS + 1)
        return {
            "ok": True,
            "columns": cols,
            "rows": [[jsonable(v) for v in r] for r in rows[:MAX_GOLD_ROWS]],
            "row_count": len(rows),
            "truncated": len(rows) > MAX_GOLD_ROWS,
            "seconds": round(time.time() - t, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc).splitlines()[0][:300], "seconds": round(time.time() - t, 2)}


def load_pool() -> list[dict]:
    pool = []
    for c in yaml.safe_load(B_GT.read_text(encoding="utf-8"))["cases"]:
        pool.append({
            "id": c["id"],
            "source": "B:" + (c.get("origem") or "nativo"),
            "question": c["question"].strip(),
            "category": c.get("category"),
            "difficulty": DIFFICULTY.get(str(c.get("difficulty", "")).lower(), c.get("difficulty")),
            "answerable": c.get("answerable", True),
            "expect_empty": bool(c.get("expect_empty")),
            "ordered": bool(c.get("ordered")),
            "must_mention": c.get("answer_must_mention") or [],
            "tests": c.get("tests"),
            "sql_original": (c.get("gold_sql") or "").strip(),
        })
    m_difficulty = {"M01": "easy", "M02": "easy", "M03": "easy", "M04": "easy", "M05": "medium",
                    "M06": "medium", "M07": "medium", "M08": "hard", "M09": "easy", "M10": "medium",
                    "M11": "easy", "M12": "medium", "M13": "medium", "M14": "easy", "M15": "medium",
                    "M16": "easy"}
    for m in json.loads(M_GT.read_text(encoding="utf-8")):
        pool.append({
            "id": m["id"], "source": "A:questions_sihrd9", "question": m["question"].strip(),
            "category": "sihrd9", "difficulty": m_difficulty.get(m["id"]), "answerable": True, "expect_empty": False,
            "ordered": False, "must_mention": [], "tests": None, "sql_original": m["sql"].strip(),
        })
    return pool


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flags", action="store_true")
    ap.add_argument("--ids", nargs="*")
    args = ap.parse_args()

    decisions = yaml.safe_load(CURATION.read_text(encoding="utf-8")) if CURATION.exists() else {}
    decisions = decisions or {}
    pool = load_pool()
    if args.ids:
        pool = [p for p in pool if p["id"] in set(args.ids)]

    items = []
    for p in pool:
        d = decisions.get(p["id"], {}) or {}
        item = dict(p)
        item["decision"] = d.get("action", "keep")
        item["reason"] = d.get("reason")
        if item["decision"] == "drop":
            items.append(item)
            continue
        if "question" in d:
            item["question"] = d["question"].strip()
        if "answerable" in d:
            item["answerable"] = d["answerable"]
        if "must_mention" in d:
            item["must_mention"] = d["must_mention"]
        if "difficulty" in d:
            item["difficulty"] = d["difficulty"]
        if "category" in d:
            item["category"] = d["category"]
        if "ordered" in d:
            item["ordered"] = d["ordered"]
        item["compare_columns"] = d.get("compare_columns")
        sql = d["sql"] if "sql" in d else (migrate(p["sql_original"]) if p["sql_original"] else "")
        sql = sql.replace("{ESPEC_LABEL}", ESPEC_LABEL)
        item["gold_sql"] = sql.strip().rstrip(";").strip() if item["answerable"] else ""
        alts = [a.replace("{ESPEC_LABEL}", ESPEC_LABEL).strip().rstrip(";").strip() for a in d.get("alternatives", [])]
        if d.get("geo_alternative") == "hospital" and item["gold_sql"]:
            alts.append(hospital_geo(item["gold_sql"]))
        for pairs in d.get("alt_replace", []):  # each entry = one alternative
            alt = item["gold_sql"]
            for old, new in pairs:
                if old not in alt:
                    raise ValueError(f"{p['id']}: alt_replace target not found: {old!r}")
                alt = alt.replace(old, new)
            alts.append(alt)
        if item["answerable"] and item["gold_sql"] and d.get("date_alternative", True):
            for base in [item["gold_sql"], *list(alts)]:
                if (alt := date_alternative(item["question"], base)):
                    alts.append(alt)
        item["alternatives"] = list(dict.fromkeys(a for a in alts if a and a != item["gold_sql"]))
        item["flags"] = sorted(
            name for name, pat in FLAG_PATTERNS.items()
            if item["gold_sql"] and re.search(pat, item["gold_sql"], re.I | re.S)
        )
        items.append(item)

    if args.flags:
        for it in items:
            if it["decision"] != "drop" and it.get("flags"):
                print(it["id"], it["flags"], "|", it["question"][:90])
        return 0

    con = duckdb.connect(str(DB), read_only=True)

    def run(it):
        if it["decision"] == "drop" or not it["answerable"] or not it["gold_sql"]:
            return it
        it["gold_result"] = execute(con, it["gold_sql"])
        it["alternative_results"] = [execute(con, a) for a in it["alternatives"]]
        return it

    with ThreadPoolExecutor(max_workers=6) as ex:
        items = list(ex.map(run, items))

    kept = [it for it in items if it["decision"] != "drop"]
    with OUT.open("w", encoding="utf-8") as fh:
        for it in kept:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")

    problems = []
    for it in kept:
        r = it.get("gold_result")
        if not it["answerable"]:
            continue
        if not r or not r["ok"]:
            problems.append((it["id"], "gold_error", (r or {}).get("error")))
        elif r["row_count"] == 0 and not it["expect_empty"]:
            problems.append((it["id"], "gold_empty", ""))
        elif r["truncated"]:
            problems.append((it["id"], "gold_over_cap", r["row_count"]))
        for a in it.get("alternative_results", []):
            if not a["ok"]:
                problems.append((it["id"], "alt_error", a["error"]))

    lines = ["# Curadoria do ground truth sihrd9", ""]
    lines.append(f"- Pool: {len(items)} casos; mantidos {len(kept)}; descartados {len(items) - len(kept)}.")
    lines.append(f"- Respondíveis: {sum(1 for i in kept if i['answerable'])}; "
                 f"irrespondíveis (avaliados só pela resposta em linguagem natural): {sum(1 for i in kept if not i['answerable'])}.")
    lines.append(f"- Com alternativa de interpretação: {sum(1 for i in kept if i.get('alternatives'))}.")
    lines.append(f"- Decisões manuais: {sum(1 for i in items if i['decision'] != 'keep')}.")
    lines.append(f"- Problemas pendentes: {len(problems)}.")
    lines.append("")
    lines.append("## Decisões manuais")
    lines.append("")
    lines.append("| id | ação | motivo |")
    lines.append("|---|---|---|")
    for it in items:
        if it["decision"] != "keep":
            lines.append(f"| {it['id']} | {it['decision']} | {(it['reason'] or '').replace('|', '/').strip()} |")
    if problems:
        lines.append("")
        lines.append("## Problemas pendentes")
        lines.append("")
        for pid, kind, detail in problems:
            lines.append(f"- {pid}: {kind} {detail or ''}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"kept={len(kept)} dropped={len(items) - len(kept)} problems={len(problems)}")
    for p in problems:
        print("  ", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
