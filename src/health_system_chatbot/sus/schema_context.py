"""Renderiza o dicionário configurado no bloco de contexto injetado no prompt."""

from __future__ import annotations

import functools
from pathlib import Path

import yaml


@functools.lru_cache(maxsize=1)
def load_schema() -> dict:
    with Path(__file__).with_name("sihrd9.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _render_table(name: str, spec: dict) -> list[str]:
    out = [f"### {name}  ({spec.get('role', '?')})"]
    if desc := spec.get("description"):
        out.append(desc)
    if rows := spec.get("rows"):
        out.append(f"Linhas: {rows:,}")
    if grain := spec.get("grain"):
        out.append(grain)

    if cols := spec.get("columns"):
        out.append("Colunas:")
        for col, meta in cols.items():
            if isinstance(meta, dict):
                t = meta.get("type", "")
                d = meta.get("desc", "")
                out.append(f"  - {col} ({t}){': ' + d if d else ''}")
            else:
                out.append(f"  - {col}: {meta}")

    if values := spec.get("values"):
        pairs = ", ".join(f"{k}={v!r}" for k, v in values.items())
        out.append(f"Domínio: {pairs}")

    if caveat := spec.get("caveat"):
        out.append(f"⚠ {caveat}")
    return out


@functools.lru_cache(maxsize=1)
def build_schema_prompt() -> str:
    """Monta o contexto completo do banco: schema + domínios + regras + exemplos."""
    s = load_schema()
    parts: list[str] = []

    db = s["database"]
    parts.append("## BANCO DE DADOS")
    parts.append(f"Engine: {db['engine']}")
    parts.append(db["dialect_notes"].strip())
    parts.append(f"Granularidade: {db['grain'].strip()}")
    parts.append(f"Período: {db['period'].strip()}")

    parts.append("\n## TABELAS")
    for name, spec in s["tables"].items():
        parts.extend(_render_table(name, spec))
        parts.append("")

    parts.append("## TABELAS PROIBIDAS (nunca consulte)")
    for name, why in s["forbidden_tables"].items():
        parts.append(f"  - {name}: {why}")

    parts.append("\n## JUNÇÕES CANÔNICAS")
    parts.extend(f"  {j}" for j in s["joins"])

    parts.append("\n## REGRAS CRÍTICAS")
    for rule in s["rules"]:
        parts.append(f"[{rule['severity'].upper()}] {rule['id']}")
        parts.append(rule["text"].strip())
        parts.append("")

    parts.append("## EXEMPLOS RESOLVIDOS")
    for ex in s["examples"]:
        parts.append(f"P: {ex['question']}")
        parts.append(f"SQL:\n{ex['sql'].strip()}")
        if note := ex.get("note"):
            parts.append(f"({note})")
        parts.append("")

    return "\n".join(parts)


@functools.lru_cache(maxsize=1)
def capability_notes() -> str:
    """Resumo curto do que a base NÃO consegue responder, para o modelo recusar bem."""
    return (
        "A base registra internações do SUS, sem identificação única de pacientes. "
        "O hospital de atendimento é identificado pelo CNES. Indicadores municipais "
        "dependem da cobertura de ano e município em socioeconomico."
    )
