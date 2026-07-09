from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


CATALOG_QUERY_STOPWORDS = {
    "acima",
    "abaixo",
    "aconteceram",
    "aconteceu",
    "anos",
    "ano",
    "cidade",
    "codigo",
    "codigos",
    "com",
    "como",
    "de",
    "da",
    "das",
    "do",
    "dos",
    "diagnostico",
    "diagnosticos",
    "em",
    "estado",
    "hospital",
    "hospitalar",
    "internacao",
    "internacoes",
    "morte",
    "mortes",
    "morreu",
    "morreram",
    "municipio",
    "obito",
    "obitos",
    "para",
    "por",
    "principal",
    "quais",
    "qual",
    "quantas",
    "quantos",
    "total",
}


def normalize_catalog_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def tokenize_catalog_query(value: str) -> list[str]:
    tokens = []
    for token in normalize_catalog_text(value).split():
        if len(token) < 3 or token in CATALOG_QUERY_STOPWORDS:
            continue
        tokens.append(token)
        if token.endswith("s") and len(token) > 5:
            tokens.append(token[:-1])
        if len(token) >= 7:
            tokens.append(token[:6])
    return _dedupe(tokens)


def load_domain_synonyms(project_root: Path | None) -> dict[str, list[str]]:
    if project_root is None:
        return {}
    path = project_root / "docs/domain_synonyms/clinical_terms.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    synonyms: dict[str, list[str]] = {}
    for key, values in payload.items():
        if not isinstance(values, list):
            continue
        normalized_key = normalize_catalog_text(str(key))
        normalized_values = [
            normalize_catalog_text(str(value)) for value in values if normalize_catalog_text(str(value))
        ]
        if normalized_key:
            synonyms[normalized_key] = _dedupe([normalized_key, *normalized_values])
    return synonyms


def expand_query_terms(query: str, synonyms: dict[str, list[str]] | None = None) -> list[str]:
    normalized = normalize_catalog_text(query)
    terms = tokenize_catalog_query(query)
    for key, values in (synonyms or {}).items():
        if key in normalized or any(value in normalized for value in values):
            terms.extend(values)
    return _dedupe(terms)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_catalog_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped
