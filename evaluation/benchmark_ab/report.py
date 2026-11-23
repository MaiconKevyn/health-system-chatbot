"""Markdown report for a scored benchmark run (any number of systems).

    python evaluation/benchmark_ab/report.py <run_dir>   -> <run_dir>/report.md
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = {
    "A": "A · health-system-chatbot (motor histórico)",
    "P": "P · health-system-chatbot (produto, motor SUS)",
    "B": "B · agent-text-to-sql-sus",
}
ORDER = ["A", "P", "B"]


def pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "—"


def wilson(n, d, z=1.96):
    if not d:
        return "—"
    p = n / d
    den = 1 + z * z / d
    c = (p + z * z / (2 * d)) / den
    h = z * math.sqrt(p * (1 - p) / d + z * z / (4 * d * d)) / den
    return f"{100 * (c - h):.0f}–{100 * (c + h):.0f}%"


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value for discordant counts b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def failure_kind(r):
    if not r.get("answerable") or r.get("ex_strict"):
        return None
    if r.get("status") == "error":
        return "exceção no pipeline"
    if r.get("refused") or not r.get("sql"):
        return "recusou / não gerou SQL"
    if not (r.get("pred_result") or {}).get("ok"):
        return "SQL não executa"
    if r.get("ex_numeric"):
        return "números certos, rótulo diferente"
    return "resultado diferente do gold"


def main() -> int:
    run = Path(sys.argv[1])
    rows = [json.loads(l) for l in (run / "scored.jsonl").open(encoding="utf-8")]
    gt = {json.loads(l)["id"]: json.loads(l) for l in (HERE / "gt_sihrd9.jsonl").open(encoding="utf-8")}
    prov_path = run / "provenance" / "provenance.json"
    prov = json.loads(prov_path.read_text()) if prov_path.exists() else {}
    by = defaultdict(dict)
    for r in rows:
        by[r["id"]][r["system"]] = r
    systems = [s for s in ORDER if any(s in v for v in by.values())]
    systems += sorted({r["system"] for r in rows} - set(systems))
    ids = sorted(i for i in by if all(s in by[i] for s in systems) and i in gt)
    ans_ids = [i for i in ids if gt[i]["answerable"]]
    una_ids = [i for i in ids if not gt[i]["answerable"]]
    hdr = " | ".join(systems)

    L = ["# Benchmark text-to-SQL — sihrd9, gpt-6-luna", ""]
    L.append(f"- Perguntas pareadas: **{len(ids)}** ({len(ans_ids)} respondíveis, {len(una_ids)} irrespondíveis), "
             "mesmas perguntas, mesmo banco, mesmo modelo e mesmo esforço de raciocínio para todos os sistemas.")
    for s in systems:
        L.append(f"- **{s}** = {NAMES.get(s, s)}")
    if prov:
        L.append(f"- Snapshot: health-system-chatbot `{prov['A']['head'][:8]}` + alterações locais · "
                 f"agent-text-to-sql-sus `{prov['B']['head'][:8]}` + alterações locais (ver `provenance/`). "
                 f"Execução: {prov.get('created_at', '')[:19]}Z.")
    L.append("- EX = acurácia de execução: o SQL final de cada sistema é reexecutado e comparado ao gold e às "
             "alternativas aceitas. NL = juiz cego sobre o texto final entregue ao usuário.")
    L.append("")

    L += ["## Resultado geral", "", f"| métrica | {hdr} |", "|---|" + "---|" * len(systems)]

    def count(fn, ids_, s):
        return sum(1 for i in ids_ if fn(by[i][s])), len(ids_)

    metrics = [
        ("EX estrito", lambda r: r.get("ex_strict"), ans_ids),
        ("EX numérico (ignora rótulos)", lambda r: r.get("ex_numeric"), ans_ids),
        ("NL correta", lambda r: r.get("nl_verdict") == "correct", ans_ids),
        ("NL correta ou parcial", lambda r: r.get("nl_verdict") in ("correct", "partially_correct"), ans_ids),
        ("Texto fiel ao próprio resultado", lambda r: r.get("nl_faithful") == "yes", ans_ids),
        ("Irrespondíveis tratados corretamente", lambda r: r.get("nl_verdict") == "correct", una_ids),
    ]
    for name, fn, ids_ in metrics:
        cells = []
        for s in systems:
            n, d = count(fn, ids_, s)
            cells.append(f"{pct(n, d)} ({n}/{d}; IC95 {wilson(n, d)})")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    q = lambda xs, p: xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else 0
    lat = {s: sorted(by[i][s].get("latency_s") or 0 for i in ids) for s in systems}
    L.append("| Latência p50 / p90 | " + " | ".join(f"{q(lat[s], .5):.1f}s / {q(lat[s], .9):.1f}s" for s in systems) + " |")
    L.append("")

    L += ["## Confronto pareado (teste de McNemar exato)", ""]
    for a, b in itertools.combinations(systems, 2):
        for label, key in (("EX estrito", lambda r: bool(r.get("ex_strict"))),
                           ("NL correta", lambda r: r.get("nl_verdict") == "correct")):
            both = sum(1 for i in ans_ids if key(by[i][a]) and key(by[i][b]))
            only_a = sum(1 for i in ans_ids if key(by[i][a]) and not key(by[i][b]))
            only_b = sum(1 for i in ans_ids if not key(by[i][a]) and key(by[i][b]))
            none = len(ans_ids) - both - only_a - only_b
            p = mcnemar_exact(only_a, only_b)
            verdict = "diferença significativa a 5%" if p < 0.05 else "sem diferença significativa a 5%"
            L.append(f"- **{a} × {b} — {label}**: ambos acertam {both} · só {a} {only_a} · só {b} {only_b} · "
                     f"ambos erram {none} · p = {p:.4f} ({verdict})")
    L.append("")

    L += ["## Execução × resposta final", "",
          "Separa erro de SQL de erro de redação: \"EX ok, NL não correta\" = o SQL estava certo e o texto não.", "",
          f"| | {hdr} |", "|---|" + "---|" * len(systems)]
    for name, ex, nl in (("EX ok, NL correta", True, True), ("EX ok, NL não correta", True, False),
                         ("EX falhou, NL correta", False, True), ("EX falhou, NL não correta", False, False)):
        cells = []
        for s in systems:
            n = sum(1 for i in ans_ids if bool(by[i][s].get("ex_strict")) == ex
                    and (by[i][s].get("nl_verdict") == "correct") == nl)
            cells.append(f"{n} ({pct(n, len(ans_ids))})")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    L.append("")

    for title, field in (("Por dificuldade", "difficulty"), ("Por categoria", "category")):
        L += [f"## {title}", "", "| grupo | n | " + " | ".join(f"EX {s}" for s in systems) + " | "
              + " | ".join(f"NL {s}" for s in systems) + " |", "|---|---|" + "---|" * (2 * len(systems))]
        groups = defaultdict(list)
        for i in ans_ids:
            groups[str(gt[i].get(field) or "—")].append(i)
        for g, gi in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            ex = [pct(sum(1 for i in gi if by[i][s].get("ex_strict")), len(gi)) for s in systems]
            nl = [pct(sum(1 for i in gi if by[i][s].get("nl_verdict") == "correct"), len(gi)) for s in systems]
            L.append(f"| {g} | {len(gi)} | " + " | ".join(ex) + " | " + " | ".join(nl) + " |")
        L.append("")

    L += ["## Tipos de falha (EX)", "", f"| tipo | {hdr} |", "|---|" + "---|" * len(systems)]
    kinds = {s: Counter(failure_kind(by[i][s]) for i in ans_ids) for s in systems}
    for k in sorted({k for s in kinds for k in kinds[s] if k}):
        L.append(f"| {k} | " + " | ".join(str(kinds[s].get(k, 0)) for s in systems) + " |")
    L.append("")

    L += ["## Onde os sistemas divergem (EX)", "", f"| id | pergunta | {hdr} |", "|---|---|" + "---|" * len(systems)]
    for i in ans_ids:
        vals = [bool(by[i][s].get("ex_strict")) for s in systems]
        if len(set(vals)) == 1:
            continue
        cells = [("✅" if by[i][s].get("ex_strict") else "❌") + f" {by[i][s].get('nl_verdict') or ''}" for s in systems]
        L.append(f"| {i} | {gt[i]['question'][:90].replace('|', '/')} | " + " | ".join(cells) + " |")
    L.append("")
    L += ["## Irrespondíveis", "", f"| id | pergunta | {hdr} |", "|---|---|" + "---|" * len(systems)]
    for i in una_ids:
        L.append(f"| {i} | {gt[i]['question'][:90]} | " + " | ".join(str(by[i][s].get('nl_verdict')) for s in systems) + " |")
    L.append("")
    (run / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(run / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
