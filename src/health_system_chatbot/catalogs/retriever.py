from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

from ..config import ChatbotConfig
from .clinical_concepts import ClinicalConcept, load_clinical_concepts
from .duckdb_store import DuckDbCatalogStore
from .models import CatalogCandidate, CatalogFilter, CatalogSearchResult, CatalogToolCall
from .normalization import (
    CATALOG_QUERY_STOPWORDS,
    expand_query_terms,
    load_domain_synonyms,
    normalize_catalog_text,
    normalize_code,
)
from .procedure_concepts import ProcedureConcept, load_procedure_concepts
from ..errors import CatalogBudgetExceeded


# `internacao` has no procedure column: procedures live in
# internacao_procedimento, which repeats rows for long-stay AIHs, so filters are
# expressed as a semi-join that keeps the hospitalization grain.
PROCEDURE_IN_TEMPLATE = (
    "EXISTS (SELECT 1 FROM internacao_procedimento ip "
    "WHERE ip.N_AIH = i.N_AIH AND ip.PROC_REA IN (...))"
)
PROCEDURE_EQ_TEMPLATE = (
    "EXISTS (SELECT 1 FROM internacao_procedimento ip "
    "WHERE ip.N_AIH = i.N_AIH AND ip.PROC_REA = ?)"
)

DIMENSION_SPECS: dict[str, tuple[str, ...]] = {
    "municipios": ("CO_MUNICIPIO_6D", "NO_MUNICIPIO", "SG_UF"),
    "hospital": ("CNES", "NO_HOSPITAL", "MUNIC_MOV"),
    "especialidade": ("ESPEC", "DESCRICAO"),
    "sexo": ("SEXO", "DESCRICAO"),
    "car_int": ("CAR_INT", "DESCRICAO"),
    "complexidade": ("COMPLEX", "DESCRICAO"),
    "marca_uti": ("MARCA_UTI", "DESCRICAO"),
    "raca_cor": ("RACA_COR", "DESCRICAO"),
    "instrucao": ("INSTRU", "DESCRICAO"),
    "vincprev": ("VINCPREV", "DESCRICAO"),
    "nacionalidade": ("NACIONAL", "DESCRICAO"),
    "contraceptivos": ("CONTRACEPTIVO", "DESCRICAO"),
}


class CatalogRetriever:
    def __init__(
        self,
        *,
        store: DuckDbCatalogStore,
        project_root: Path | None = None,
        retrieval_mode: str = "lexical",
        tool_call_budget: int = 8,
        duplicate_call_limit: int = 1,
    ) -> None:
        if retrieval_mode != "lexical":
            raise ValueError("CatalogRetriever currently supports only lexical retrieval.")
        self.store = store
        self.project_root = project_root
        self.retrieval_mode = retrieval_mode
        self.synonyms = store.synonyms
        self.clinical_concepts = load_clinical_concepts(project_root)
        self.procedure_concepts = load_procedure_concepts(project_root)
        self.tool_calls: list[CatalogToolCall] = []
        self.tool_call_budget = tool_call_budget
        self.duplicate_call_limit = duplicate_call_limit
        self._call_signatures: dict[str, int] = {}

    @classmethod
    def from_config(cls, config: ChatbotConfig) -> "CatalogRetriever":
        synonyms = load_domain_synonyms(config.project_root)
        return cls(
            store=DuckDbCatalogStore(config.db_path, synonyms=synonyms),
            project_root=config.project_root,
            retrieval_mode=config.catalog_retrieval_mode,
            tool_call_budget=config.catalog_tool_call_budget,
            duplicate_call_limit=config.catalog_duplicate_call_limit,
        )

    def guard_tool_call(self, *, tool: str, args: dict[str, Any]) -> None:
        signature = tool + ":" + json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
        repeated = self._call_signatures.get(signature, 0)
        if repeated >= self.duplicate_call_limit:
            message = f"catalog_duplicate_call:{tool}; signature already used {repeated} time(s)"
            self.record_tool_call(tool=tool, args=args, error=message)
            raise CatalogBudgetExceeded(message)
        if len(self.tool_calls) >= self.tool_call_budget:
            message = f"catalog_tool_budget_exceeded:{self.tool_call_budget}"
            self.record_tool_call(tool=tool, args=args, error=message)
            raise CatalogBudgetExceeded(message)
        self._call_signatures[signature] = repeated + 1

    def record_tool_call(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        result: CatalogSearchResult | None = None,
        error: str | None = None,
    ) -> None:
        self.tool_calls.append(
            CatalogToolCall(
                tool=tool,
                args=args,
                result=result,
                error=error,
            )
        )

    def search_cid(
        self,
        query: str,
        *,
        scope: str = "unknown",
        limit: int = 5,
    ) -> CatalogSearchResult:
        warnings: list[str] = []
        candidates = self._cid_prefix_candidates(query)
        candidates.extend(self._clinical_concept_candidates(query, scope=scope))
        rows = self.store.search_cid_rows(query, limit=0)
        candidates.extend(self._cid_candidates_from_rows(query, rows, scope=scope))
        candidates = _dedupe_candidates(candidates)
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        if not candidates:
            warnings.append("No CID candidates matched the local catalog.")
        return CatalogSearchResult(
            query=query,
            catalog="cid",
            candidates=candidates[:limit],
            warnings=warnings,
        )

    def search_procedures(
        self,
        query: str,
        *,
        scope: str = "unknown",
        limit: int = 5,
    ) -> CatalogSearchResult:
        concept_matches = self._procedure_concept_matches(query, scope=scope)
        concept_candidates = [candidate for candidate, _ in concept_matches]
        fully_covered = any(not uncovered for _, uncovered in concept_matches)
        if concept_candidates and fully_covered:
            concept_candidates.sort(key=lambda candidate: candidate.score, reverse=True)
            return CatalogSearchResult(
                query=query,
                catalog="procedimentos",
                candidates=concept_candidates[:limit],
                warnings=[],
            )

        rows = self.store.search_procedure_rows(query, limit=0)
        query_term_groups = _strict_query_term_groups(query)
        strict_rows = [
            row
            for row in rows
            if query_term_groups
            and all(
                any(_term_matches_text(term, str(row.get("NOME_PROC") or "")) for term in group)
                for group in query_term_groups
            )
        ]
        warnings: list[str] = []
        if concept_candidates:
            # A curated concept matched only part of the query ("parto" in
            # "parto espontaneo cefalico"). Loose rows would be noise, so only
            # rows matching every term, or a CID with that exact description,
            # count as a more specific reading of the term.
            qualifiers = sorted({term for _, uncovered in concept_matches for term in uncovered})
            cid_candidates = self._cid_phrase_candidates(query, qualifiers)
            specific = self._procedure_row_candidates(query, strict_rows, limit=limit)
            if not cid_candidates and not specific:
                concept_candidates.sort(key=lambda candidate: candidate.score, reverse=True)
                return CatalogSearchResult(
                    query=query,
                    catalog="procedimentos",
                    candidates=concept_candidates[:limit],
                    warnings=[],
                )
            for candidate, uncovered in concept_matches:
                candidate.score -= 100.0
                candidate.confidence = "medium"
                candidate.ambiguity_notes.append(
                    "Grupo mais amplo que a pergunta: nao cobre "
                    + ", ".join(uncovered)
                    + "."
                )
            for candidate in cid_candidates:
                warnings.append(
                    f"'{query}' corresponde ao CID {candidate.code} "
                    f"'{candidate.label.removeprefix(str(candidate.code)).strip()}', "
                    "um diagnostico e nao um procedimento. Nenhum procedimento cobre "
                    f"{', '.join(qualifiers)}; filtre internacao.DIAG_PRINC = "
                    f"'{candidate.code}' em vez de aproximar por PROC_REA."
                )
            candidates = _dedupe_candidates(concept_candidates + cid_candidates + specific)
            candidates.sort(key=lambda candidate: candidate.score, reverse=True)
            return CatalogSearchResult(
                query=query,
                catalog="procedimentos",
                candidates=candidates[:limit],
                warnings=warnings,
            )

        if strict_rows:
            rows = strict_rows
        candidates = _dedupe_candidates(self._procedure_row_candidates(query, rows, limit=limit))
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return CatalogSearchResult(
            query=query,
            catalog="procedimentos",
            candidates=candidates[:limit],
            warnings=[] if candidates else ["No procedure candidates matched the local catalog."],
        )

    def _procedure_row_candidates(
        self,
        query: str,
        rows: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[CatalogCandidate]:
        candidates: list[CatalogCandidate] = []
        if len(rows) > 1:
            codes = [str(row["PROC_REA"]) for row in rows[:20]]
            labels = [str(row["NOME_PROC"]) for row in rows[:8]]
            candidates.append(
                CatalogCandidate(
                    catalog="procedimentos",
                    level="group",
                    code=",".join(codes),
                    label=f"Procedimentos correspondentes a '{query}'",
                    description="Conjunto de procedimentos recuperados pelo catalogo local.",
                    source_table="procedimentos",
                    source_column="PROC_REA",
                    filter=CatalogFilter(
                        table="internacao_procedimento",
                        column="PROC_REA",
                        operator="IN",
                        value=codes,
                        join_required=True,
                        where_sql_template=PROCEDURE_IN_TEMPLATE,
                    ),
                    evidence=labels,
                    score=160.0,
                    confidence="high" if len(rows) <= 10 else "medium",
                    ambiguity_notes=[]
                    if len(rows) <= 10
                    else ["Muitos procedimentos correspondem ao termo; revisar debug."],
                )
            )
        for row in rows[:limit]:
            code = str(row["PROC_REA"])
            label = str(row["NOME_PROC"] or "")
            candidates.append(
                CatalogCandidate(
                    catalog="procedimentos",
                    level="code",
                    code=code,
                    label=label,
                    description=label,
                    source_table="procedimentos",
                    source_column="PROC_REA",
                    filter=CatalogFilter(
                        table="internacao_procedimento",
                        column="PROC_REA",
                        operator="=",
                        value=code,
                        join_required=True,
                        where_sql_template=PROCEDURE_EQ_TEMPLATE,
                    ),
                    evidence=[f"{code} {label}"],
                    score=_text_match_score(query, label) + 40.0,
                    confidence="high",
                )
            )
        return candidates

    def _cid_phrase_candidates(self, query: str, qualifiers: list[str]) -> list[CatalogCandidate]:
        """CID codes whose whole description is the query, e.g. O800 for
        "parto espontaneo cefalico", when the qualifiers are what a procedure
        concept could not cover."""
        if not qualifiers:
            return []
        candidates: list[CatalogCandidate] = []
        for row in self.store.search_cid_rows(query, limit=0):
            description = str(row.get("DESCRICAO") or "")
            description_terms = _description_terms(description)
            if not _description_covered_by_query(description, query):
                continue
            if not any(_token_variants(term) & description_terms for term in qualifiers):
                continue
            cid = str(row.get("CID") or "")
            candidate = self._code_candidate(
                query,
                expand_query_terms(query, self.synonyms),
                cid,
                description,
                str(row.get("DS_CATEGORIA") or ""),
                str(row.get("DS_GRUPO") or ""),
                str(row.get("DS_CAPITULO") or ""),
            )
            if candidate is None:
                continue
            candidate.score = max(candidate.score, 250.0 + len(description_terms))
            candidate.confidence = "high"
            candidate.ambiguity_notes.append(
                "Termo e diagnostico CID (internacao.DIAG_PRINC), nao procedimento (PROC_REA)."
            )
            candidates.append(candidate)
        return _dedupe_candidates(candidates)

    def _clinical_concept_candidates(
        self,
        query: str,
        *,
        scope: str,
    ) -> list[CatalogCandidate]:
        candidates: list[CatalogCandidate] = []
        for concept in self.clinical_concepts:
            if scope != "unknown" and scope not in concept.scopes:
                continue
            score = _clinical_concept_score(query, concept)
            if score <= 0:
                continue
            values = [f"{prefix}%" for prefix in concept.code_prefixes]
            where_sql = _prefix_any_where_sql(values)
            candidates.append(
                CatalogCandidate(
                    catalog="cid",
                    level="group" if len(values) > 1 else "code",
                    code=",".join(concept.code_prefixes),
                    label=concept.label,
                    description=concept.description,
                    source_table="cid",
                    source_column="CID",
                    filter=CatalogFilter(
                        table="internacao",
                        column="DIAG_PRINC",
                        operator="PREFIX_ANY" if len(values) > 1 else "PREFIX",
                        value=values if len(values) > 1 else values[0],
                        where_sql_template=where_sql,
                    ),
                    evidence=list(concept.evidence),
                    score=score,
                    confidence="high",
                )
            )
        return _dedupe_candidates(candidates)

    def _procedure_concept_matches(
        self,
        query: str,
        *,
        scope: str,
    ) -> list[tuple[CatalogCandidate, list[str]]]:
        """Concept candidates plus the query terms each concept leaves uncovered."""
        matches: dict[str, tuple[CatalogCandidate, list[str]]] = {}
        for concept in self.procedure_concepts:
            if scope != "unknown" and scope not in concept.scopes:
                continue
            score = _procedure_concept_score(query, concept)
            if score <= 0:
                continue
            codes = list(concept.codes)
            candidate = CatalogCandidate(
                catalog="procedimentos",
                level="group",
                code=",".join(codes),
                label=concept.label,
                description=concept.description,
                source_table="procedimentos",
                source_column="PROC_REA",
                filter=CatalogFilter(
                    table="internacao_procedimento",
                    column="PROC_REA",
                    operator="IN",
                    value=codes,
                    join_required=True,
                    where_sql_template=PROCEDURE_IN_TEMPLATE,
                ),
                evidence=list(concept.evidence),
                score=score,
                confidence="high",
            )
            key = str(candidate.filter.value)
            if key not in matches or candidate.score > matches[key][0].score:
                matches[key] = (candidate, _uncovered_query_terms(query, concept.synonyms))
        return list(matches.values())

    def search_dimension_values(
        self,
        *,
        table: str,
        query: str,
        limit: int = 5,
    ) -> CatalogSearchResult:
        columns = DIMENSION_SPECS.get(table)
        if columns is None:
            return CatalogSearchResult(
                query=query,
                catalog="dimension",
                warnings=[f"Unsupported dimension table: {table}"],
            )
        rows = self.store.search_dimension_rows(
            table=table,
            columns=columns,
            query=query,
            limit=50,
        )
        candidates: list[CatalogCandidate] = []
        key_column, label_column = columns[0], columns[1]
        for row in rows:
            key = row.get(key_column)
            label = str(row.get(label_column) or "")
            evidence = [f"{key_column}={key}; {label_column}={label}"]
            if len(columns) > 2:
                evidence[0] += "; " + "; ".join(
                    f"{column}={row.get(column)}" for column in columns[2:]
                )
            candidates.append(
                CatalogCandidate(
                    catalog="municipios" if table == "municipios" else "dimension",
                    level="value",
                    code=str(key) if key is not None else None,
                    label=label,
                    description=evidence[0],
                    source_table=table,
                    source_column=label_column,
                    filter=CatalogFilter(
                        table=table,
                        column=label_column,
                        operator="=",
                        value=label,
                        join_required=True,
                        where_sql_template=f"{table}.{label_column} = ?",
                    ),
                    evidence=evidence,
                    score=_text_match_score(query, label) + 30.0,
                    confidence="high",
                )
            )
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return CatalogSearchResult(
            query=query,
            catalog="municipios" if table == "municipios" else "dimension",
            candidates=candidates[:limit],
            warnings=[] if candidates else [f"No values matched {table} for query '{query}'."],
        )

    def _cid_prefix_candidates(self, query: str) -> list[CatalogCandidate]:
        normalized = normalize_catalog_text(query)
        match = re.search(r"\bcid\s+([a-z][0-9]{0,2})\b", normalized)
        if not match:
            return []
        prefix = normalize_code(match.group(1))
        if not prefix:
            return []
        return [
            CatalogCandidate(
                catalog="cid",
                level="code",
                code=prefix,
                label=f"CID prefixo {prefix}",
                description="Filtro por prefixo CID explicitamente pedido pelo usuario.",
                source_table="cid",
                source_column="CID",
                filter=CatalogFilter(
                    table="internacao",
                    column="DIAG_PRINC",
                    operator="PREFIX",
                    value=f"{prefix}%",
                    where_sql_template="i.DIAG_PRINC LIKE ?",
                ),
                evidence=[f"Pergunta menciona CID {prefix}"],
                score=120.0,
                confidence="high",
            )
        ]

    def _cid_candidates_from_rows(
        self,
        query: str,
        rows: list[dict[str, Any]],
        *,
        scope: str,
    ) -> list[CatalogCandidate]:
        broad_scope = scope in {"death_cause", "diagnosis", "unknown"}
        terms = expand_query_terms(query, self.synonyms)
        best: dict[tuple[str, str], CatalogCandidate] = {}
        for row in rows:
            cid = str(row.get("CID") or "")
            description = str(row.get("DESCRICAO") or "")
            category = str(row.get("DS_CATEGORIA") or "")
            group = str(row.get("DS_GRUPO") or "")
            chapter = str(row.get("DS_CAPITULO") or "")

            if chapter:
                self._keep_best(
                    best,
                    self._chapter_candidate(query, terms, cid, description, chapter, broad_scope),
                )
            if group:
                self._keep_best(
                    best,
                    self._group_candidate(query, terms, cid, description, group, chapter),
                )
            if category:
                self._keep_best(
                    best,
                    self._category_candidate(query, terms, cid, description, category, chapter),
                )
            self._keep_best(
                best,
                self._code_candidate(query, terms, cid, description, category, group, chapter),
            )
        return list(best.values())

    def _chapter_candidate(
        self,
        query: str,
        terms: list[str],
        cid: str,
        description: str,
        chapter: str,
        broad_scope: bool,
    ) -> CatalogCandidate | None:
        del query
        score = _field_score(terms, chapter)
        if score <= 0:
            return None
        level_bonus = 70.0 if broad_scope else 50.0
        return CatalogCandidate(
            catalog="cid",
            level="chapter",
            code=_chapter_code(chapter),
            label=chapter,
            description=chapter,
            source_table="cid",
            source_column="DS_CAPITULO",
            filter=CatalogFilter(
                table="cid",
                column="DS_CAPITULO",
                operator="=",
                value=chapter,
                join_required=True,
                join_sql="JOIN cid c ON i.DIAG_PRINC = c.CID",
                where_sql_template="c.DS_CAPITULO = ?",
            ),
            evidence=[f"exemplo={cid} {description}"],
            score=score + level_bonus,
            confidence=_confidence(score + level_bonus),
        )

    def _group_candidate(
        self,
        query: str,
        terms: list[str],
        cid: str,
        description: str,
        group: str,
        chapter: str,
    ) -> CatalogCandidate | None:
        score = _field_score(terms, group)
        if score <= 0:
            return None
        group_code, group_label = _split_code_label(group)
        exact_tail_bonus = 55.0 if _tail_matches_query(group_label, query) else 0.0
        return CatalogCandidate(
            catalog="cid",
            level="group",
            code=group_code,
            label=group,
            description=group_label,
            source_table="cid",
            source_column="DS_GRUPO",
            filter=CatalogFilter(
                table="cid",
                column="DS_GRUPO",
                operator="=",
                value=group,
                join_required=True,
                join_sql="JOIN cid c ON i.DIAG_PRINC = c.CID",
                where_sql_template="c.DS_GRUPO = ?",
            ),
            evidence=[f"exemplo={cid} {description}; capitulo={chapter}"],
            score=score + 60.0 + exact_tail_bonus,
            confidence=_confidence(score + 60.0 + exact_tail_bonus),
        )

    def _category_candidate(
        self,
        query: str,
        terms: list[str],
        cid: str,
        description: str,
        category: str,
        chapter: str,
    ) -> CatalogCandidate | None:
        score = max(_field_score(terms, category), _field_score(terms, description) - 10.0)
        if score <= 0:
            return None
        return CatalogCandidate(
            catalog="cid",
            level="category",
            code=cid[:3] if len(cid) >= 3 else cid,
            label=category,
            description=description,
            source_table="cid",
            source_column="DS_CATEGORIA",
            filter=CatalogFilter(
                table="cid",
                column="DS_CATEGORIA",
                operator="=",
                value=category,
                join_required=True,
                join_sql="JOIN cid c ON i.DIAG_PRINC = c.CID",
                where_sql_template="c.DS_CATEGORIA = ?",
            ),
            evidence=[f"{cid} {description}; capitulo={chapter}"],
            score=score + 40.0,
            confidence=_confidence(score + 40.0),
        )

    def _code_candidate(
        self,
        query: str,
        terms: list[str],
        cid: str,
        description: str,
        category: str,
        group: str,
        chapter: str,
    ) -> CatalogCandidate | None:
        score = max(
            _code_score(query, cid),
            _field_score(terms, description),
            _field_score(terms, category) - 5.0,
        )
        if score <= 0:
            return None
        if _description_covered_by_query(description, query):
            # "parto espontaneo cefalico" names O800 exactly; without this the
            # broader O80 category ties with it and wins on sort order.
            score += 40.0
        operator = "PREFIX" if len(cid) <= 3 else "="
        value = f"{cid}%" if operator == "PREFIX" else cid
        where = "i.DIAG_PRINC LIKE ?" if operator == "PREFIX" else "i.DIAG_PRINC = ?"
        return CatalogCandidate(
            catalog="cid",
            level="code",
            code=cid,
            label=f"{cid} {description}".strip(),
            description=f"categoria={category}; grupo={group}; capitulo={chapter}",
            source_table="cid",
            source_column="CID",
            filter=CatalogFilter(
                table="internacao",
                column="DIAG_PRINC",
                operator=operator,
                value=value,
                where_sql_template=where,
            ),
            evidence=[f"{cid} {description}; grupo={group}; capitulo={chapter}"],
            score=score + 30.0,
            confidence=_confidence(score + 30.0),
        )

    @staticmethod
    def _keep_best(
        best: dict[tuple[str, str], CatalogCandidate],
        candidate: CatalogCandidate | None,
    ) -> None:
        if candidate is None:
            return
        key = (candidate.source_column, str(candidate.filter.value))
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate


def _field_score(terms: list[str], value: str) -> float:
    normalized = normalize_catalog_text(value)
    if not normalized:
        return 0.0
    score = 0.0
    for term in terms:
        if term == normalized:
            score += 45.0
        elif f" {term} " in f" {normalized} ":
            score += 35.0
        elif term in normalized:
            score += 20.0
        elif len(term) >= 6 and term[:6] in normalized:
            score += 15.0
    return score


def _term_matches_text(term: str, value: str) -> bool:
    normalized = normalize_catalog_text(value)
    return term in normalized or (len(term) >= 6 and term[:6] in normalized)


def _strict_query_term_groups(query: str) -> list[list[str]]:
    groups: list[list[str]] = []
    for token in normalize_catalog_text(query).split():
        if len(token) < 3 or token in CATALOG_QUERY_STOPWORDS:
            continue
        variants = [token]
        if token.endswith("s") and len(token) > 5:
            variants.append(token[:-1])
        if len(token) >= 7:
            variants.append(token[:6])
        groups.append(list(dict.fromkeys(variants)))
    return groups


def _text_match_score(query: str, value: str) -> float:
    return _field_score(expand_query_terms(query), value)


def _clinical_concept_score(query: str, concept: ClinicalConcept) -> float:
    return _synonym_concept_score(query, concept.synonyms)


def _procedure_concept_score(query: str, concept: ProcedureConcept) -> float:
    return _synonym_concept_score(query, concept.synonyms)


def _synonym_concept_score(query: str, synonyms: tuple[str, ...]) -> float:
    normalized_query = normalize_catalog_text(query)
    query_terms = set(expand_query_terms(query))
    best = 0.0
    for synonym in synonyms:
        synonym_terms = set(expand_query_terms(synonym))
        if synonym and synonym == normalized_query:
            best = max(best, 260.0 + len(synonym_terms))
        elif synonym and f" {synonym} " in f" {normalized_query} ":
            best = max(best, 230.0 + len(synonym_terms))
        elif synonym_terms and synonym_terms <= query_terms:
            best = max(best, 190.0 + len(synonym_terms))
        elif synonym_terms & query_terms:
            best = max(best, 120.0 + len(synonym_terms & query_terms))
    return best


def _content_terms(text: str) -> list[str]:
    return [
        token
        for token in normalize_catalog_text(text).split()
        if len(token) >= 3 and token not in CATALOG_QUERY_STOPWORDS
    ]


def _token_variants(token: str) -> set[str]:
    variants = {token}
    if token.endswith("s") and len(token) > 4:
        variants.add(token[:-1])
    return variants


def _description_terms(description: str) -> set[str]:
    return set(_content_terms(description))


def _description_covered_by_query(description: str, query: str) -> bool:
    """True when every content word of a (multi-word) description is in the query."""
    description_terms = _description_terms(description)
    if len(description_terms) < 2:
        return False
    query_terms = {variant for term in _content_terms(query) for variant in _token_variants(term)}
    return description_terms <= query_terms


def _uncovered_query_terms(query: str, synonyms: tuple[str, ...]) -> list[str]:
    covered = {
        variant
        for synonym in synonyms
        for term in _content_terms(synonym)
        for variant in _token_variants(term)
    }
    return [term for term in _content_terms(query) if not (_token_variants(term) & covered)]


def _prefix_any_where_sql(values: list[str]) -> str:
    parts = [f"i.DIAG_PRINC LIKE '{value}'" for value in values]
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def _code_score(query: str, code: str) -> float:
    query_code = normalize_code(query)
    code_text = normalize_code(code)
    if not query_code or not code_text:
        return 0.0
    if query_code == code_text:
        return 80.0
    if code_text.startswith(query_code) and len(query_code) >= 3:
        return 50.0
    return 0.0


def _confidence(score: float) -> str:
    if score >= 95:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _split_code_label(value: str) -> tuple[str | None, str]:
    match = re.match(r"^([A-Z][0-9]{2}(?:-[A-Z]?[0-9]{2})?)\s+(.+)$", value.strip())
    if not match:
        return None, value.strip()
    return match.group(1), match.group(2)


def _chapter_code(value: str) -> str | None:
    match = re.match(r"^([IVXLCDM]+)\.", value.strip(), flags=re.I)
    return match.group(1) if match else None


def _tail_matches_query(label: str, query: str) -> bool:
    normalized_label = normalize_catalog_text(label)
    normalized_query = normalize_catalog_text(query)
    if not normalized_label or not normalized_query:
        return False
    if normalized_label == normalized_query:
        return True
    return normalized_label in set(expand_query_terms(query, {}))


def _dedupe_candidates(candidates: list[CatalogCandidate]) -> list[CatalogCandidate]:
    best: dict[tuple[str, str, str], CatalogCandidate] = {}
    for candidate in candidates:
        key = (
            candidate.catalog,
            candidate.source_column,
            str(candidate.filter.value),
        )
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return list(best.values())
