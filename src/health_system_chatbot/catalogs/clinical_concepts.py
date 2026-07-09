from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .normalization import normalize_catalog_text, normalize_code


@dataclass(frozen=True)
class ClinicalConcept:
    id: str
    label: str
    description: str
    scopes: tuple[str, ...]
    synonyms: tuple[str, ...]
    code_prefixes: tuple[str, ...]
    evidence: tuple[str, ...]


def load_clinical_concepts(project_root: Path | None) -> tuple[ClinicalConcept, ...]:
    if project_root is None:
        return ()
    path = project_root / "docs/domain_catalogs/clinical_concepts.json"
    if not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    concepts: list[ClinicalConcept] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        code_prefixes = tuple(
            code
            for code in (
                normalize_code(str(value)) for value in item.get("code_prefixes", [])
            )
            if code
        )
        synonyms = tuple(
            synonym
            for synonym in (
                normalize_catalog_text(str(value)) for value in item.get("synonyms", [])
            )
            if synonym
        )
        if not code_prefixes or not synonyms:
            continue
        concepts.append(
            ClinicalConcept(
                id=str(item.get("id") or ""),
                label=str(item.get("label") or ""),
                description=str(item.get("description") or ""),
                scopes=tuple(str(value) for value in item.get("scopes", ["unknown"])),
                synonyms=synonyms,
                code_prefixes=code_prefixes,
                evidence=tuple(str(value) for value in item.get("evidence", [])),
            )
        )
    return tuple(concepts)
