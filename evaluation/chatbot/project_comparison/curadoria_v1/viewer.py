"""Render the scored pairs as a standalone Portuguese comparison report."""

import argparse
import csv
import json
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = {"health": "health-system-chatbot", "sus": "agent-text-to-sql-sus"}
GRADES = {
    "correta": "Correta",
    "parcial": "Parcial",
    "incorreta": "Incorreta",
    "sem_resposta": "Sem resposta",
}


def answer_cell(row, project, name):
    grade = row[f"{project}_avaliacao_nl"]
    sql = row[f"{project}_sql"]
    status = "equivalente" if row[f"{project}_ex"] == "True" else "divergente"
    if not sql:
        status = "sem SQL final"
    elif row.get(f"{project}_executavel") == "False":
        status = "falhou na reexecução"
    return f"""<article><h3>{escape(name)}</h3>
    <p class="grades"><strong class="{grade}">{GRADES[grade]}</strong> · SQL {status}</p>
    <p class="answer">{escape(row[f"{project}_resposta"] or "Sem texto devolvido.")}</p>
    <p class="why">{escape(row[f"{project}_motivo"])}</p>
    <details><summary>SQL gerado</summary><pre>{escape(sql or "Sem SQL final.")}</pre></details></article>"""


def main(folder=HERE, names=NAMES):
    with (folder / "comparacao.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    stats = json.loads((folder / "summary.json").read_text())["totals"]
    table = []
    for project, name in names.items():
        table.append(
            f"<tr><th>{name}</th><td>{stats[project]['nl']}/{len(rows)}</td><td>{stats[project]['ex']}/{len(rows)}</td></tr>"
        )
    pairs = []
    for r in rows:
        error = any(r[f"{p}_avaliacao_nl"] != "correta" for p in names)
        discord = len({r[f"{p}_avaliacao_nl"] for p in names}) > 1
        cells = "".join(
            answer_cell(r, project, name) for project, name in names.items()
        )
        pairs.append(f"""<section data-error="{int(error)}" data-discord="{int(discord)}">
        <header><span>{r.get("id") or r["caso"]} · Rodada {r["rodada"]}</span><h2>{escape(r["pergunta"])}</h2></header>
        <p class="gold"><b>Resposta de referência</b>{escape(r["referencia"])}</p>
        <div class="answers">{cells}</div></section>""")
    html = """<!DOCTYPE html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comparação das respostas sobre o SIHRD9</title><style>
*{box-sizing:border-box}body{margin:auto;max-width:1140px;padding:28px 20px 80px;background:#f7f8f6;color:#1c2928;font:16px/1.5 'Source Sans 3',Arial,sans-serif}h1,h2,h3,p{margin:0 0 .55em}h1{font-size:clamp(1.7rem,4vw,2.6rem);letter-spacing:-.035em}h2{font-size:1.15rem;line-height:1.35}h3{font-size:.98rem}header span,.grades,.why,.intro{font-size:.9rem;color:#495c58}.grades{margin-bottom:14px}.correta{color:#135c46}.incorreta,.sem_resposta{color:#8b2434}.parcial{color:#735211}table{margin:1rem 0 1.3rem;border-collapse:collapse}td,th{text-align:left;border-bottom:1px solid #cdd6d2;padding:.4rem .8rem .4rem 0}label{display:inline-flex;align-items:center;gap:.5rem;margin:0 1em .5rem 0}input,select{font:inherit;border:1px solid #9ca9a3;background:white;border-radius:4px;padding:.3em;max-width:100%}section{background:#fff;border:1px solid #cdd6d2;border-radius:6px;padding:18px;margin:1rem 0}.gold{background:#eaf1ed;padding:.65rem .8rem}.gold b{font-size:.85rem;display:block}.answers{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,290px),1fr));gap:1.2rem;margin-top:16px}article{min-width:0}.answer,pre{white-space:pre-wrap;overflow-wrap:anywhere}.why{border-left:2px solid #c9d7d1;padding-left:.65rem}summary{cursor:pointer;font-size:.85rem}pre{font-size:.8rem}section[hidden]{display:none}output{font-size:.9rem}@media(max-width:720px){.answers{grid-template-columns:1fr}body{padding:15px}label{display:block}}
</style><main><h1>Comparação das respostas sobre o SIHRD9</h1>
<p class="intro">32 perguntas · duas rodadas por projeto · Luna 6 em todas as chamadas</p>
<table><thead><tr><th>Projeto</th><th>Respostas corretas</th><th>Execution accuracy</th></tr></thead><tbody>TABLE</tbody></table>
<label>Mostrar <select id="filter"><option value="all">Todas as rodadas</option><option value="error">Com falha em linguagem natural</option><option value="discord">Com avaliações diferentes</option></select></label>
<label>Buscar pergunta <input id="search" type="search"></label><output id="count" aria-live="polite"></output>
PAIRS</main><script>
const filter=document.querySelector('#filter'),search=document.querySelector('#search'),sections=[...document.querySelectorAll('section')];
const norm=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
function update(){let n=0;for(const s of sections){const match=filter.value==='all'||s.dataset[filter.value]==='1';s.hidden=!(match&&norm(s.querySelector('header').textContent).includes(norm(search.value)));if(!s.hidden)n++}document.querySelector('#count').textContent=n+' de '+sections.length}
filter.addEventListener('change',update);search.addEventListener('input',update);update();
</script></html>"""
    (folder / "comparacao.html").write_text(
        html.replace("TABLE", "".join(table)).replace("PAIRS", "".join(pairs)),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--three-arm", type=Path, metavar="RESULTS")
    folder = parser.parse_args().three_arm
    if folder:
        main(
            folder,
            {"integrated": "SUS integrado", "sus": "SUS original", "health": "Legado"},
        )
    else:
        main()
