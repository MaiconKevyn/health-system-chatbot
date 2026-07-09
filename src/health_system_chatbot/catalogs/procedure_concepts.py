from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .normalization import normalize_catalog_text, normalize_code


@dataclass(frozen=True)
class ProcedureConcept:
    id: str
    label: str
    description: str
    scopes: tuple[str, ...]
    synonyms: tuple[str, ...]
    codes: tuple[str, ...]
    evidence: tuple[str, ...]


def load_procedure_concepts(project_root: Path | None) -> tuple[ProcedureConcept, ...]:
    if project_root is None:
        return ()
    path = project_root / "docs/domain_catalogs/procedure_concepts.json"
    if not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    concepts: list[ProcedureConcept] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        codes = tuple(
            code
            for code in (normalize_code(str(value)) for value in item.get("codes", []))
            if code
        )
        synonyms = tuple(
            synonym
            for synonym in (
                normalize_catalog_text(str(value)) for value in item.get("synonyms", [])
            )
            if synonym
        )
        if not codes or not synonyms:
            continue
        concepts.append(
            ProcedureConcept(
                id=str(item.get("id") or ""),
                label=str(item.get("label") or ""),
                description=str(item.get("description") or ""),
                scopes=tuple(str(value) for value in item.get("scopes", ["unknown"])),
                synonyms=synonyms,
                codes=codes,
                evidence=tuple(str(value) for value in item.get("evidence", [])),
            )
        )
    return tuple(concepts)
