from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parents[1]
AUDIT_PATH = RUN_DIR / "audit/failure_audit.json"
RESULTS_PATH = RUN_DIR / "variants/full_agent/results.json"

THEMES_BY_ID = {
    "GT044": ["uti_definition"],
    "GT049": ["date_basis"],
    "GT078": ["diagnosis_grain"],
    "GT084": ["age_taxonomy"],
    "GT085": ["comparator_projection"],
    "GT086": ["top_n_per_group", "minimum_support"],
    "GT087": ["date_basis"],
    "GT089": ["obstetric_definition"],
    "GT090": ["diagnosis_grain"],
    "GT093": ["date_basis"],
    "GT114": ["obstetric_definition", "catalog_misuse"],
    "GT115": ["comparator_ties"],
    "GT117": ["uti_definition", "sex_mapping", "temporal_join_coverage"],
    "GT118": ["uti_definition"],
    "GT119": ["uti_definition"],
    "GT120": ["temporal_grain", "denominator"],
    "GT125": ["uti_definition", "temporal_dimension_retrieval"],
    "GT127": ["temporal_join_coverage", "diagnosis_grain"],
    "GT128": ["uti_definition", "rate_scale"],
    "GT130": ["obstetric_definition"],
    "GT131": ["indigenous_mapping"],
    "GT132": ["hidden_limit_threshold", "top_n_per_group"],
    "GT133": ["uti_definition"],
    "GT201": ["date_basis", "clinical_concept"],
    "GT202": ["age_taxonomy", "clinical_concept"],
    "GT203": ["temporal_join_coverage", "output_shape"],
    "GT205": ["hidden_limit_threshold", "rate_scale"],
    "GT207": ["uti_definition", "minimum_support", "diagnosis_grain"],
    "GT208": ["diagnosis_grain", "hidden_limit_threshold"],
    "GT210": ["hidden_limit_threshold", "ordering"],
    "GT211": ["date_basis"],
    "GT212": ["date_basis", "uti_definition"],
    "GT213": ["age_taxonomy", "output_shape"],
    "GT215": ["hidden_limit_threshold"],
    "GT216": ["hidden_time_window"],
    "GT218": ["hidden_limit_threshold", "minimum_support"],
    "GT219": ["hidden_limit_threshold", "minimum_support", "date_basis"],
    "GT220": ["temporal_grain"],
    "GT222": ["socioeconomic_coverage", "denominator"],
    "GT223": ["tool_loop"],
    "GT224": ["socioeconomic_coverage"],
    "GT225": ["age_taxonomy"],
    "GT226": ["uti_definition", "cumulative_threshold"],
    "GT227": ["age_taxonomy", "top_n_per_group"],
    "GT230": ["metric_formula", "hidden_limit_threshold"],
    "GT231": ["temporal_join_coverage", "output_shape"],
    "GT232": ["quality_rule_threshold"],
    "GT234": ["hidden_limit_threshold", "percentile_boundary"],
}


def load_records(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload.get("records") or payload.get("results") or []
    return payload


def main() -> None:
    audit_payload = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    audited = audit_payload["cases"]
    records = load_records(RESULTS_PATH)
    by_id = {record["id"]: record for record in records}

    failure_ids = {record["id"] for record in records if record.get("result_match") is not True}
    audited_ids = {case["id"] for case in audited}
    assert len(records) == 73
    assert len(failure_ids) == 48
    assert audited_ids == failure_ids
    assert set(THEMES_BY_ID) == failure_ids

    categories = Counter(case["audit_category"] for case in audited)
    layers = Counter(case["primary_layer"] for case in audited)
    confidence = Counter(case["confidence"] for case in audited)
    themes = Counter(theme for case_id in failure_ids for theme in THEMES_BY_ID[case_id])

    strict_matches = sum(record.get("result_match") is True for record in records)
    accepted_additional = categories["format_only"] + categories["acceptable_alternative_rejected"]
    indeterminate = categories["question_underspecified"] + categories["ground_truth_problem"]
    confirmed_agent_errors = categories["agent_semantic_error"]
    operational_failures = categories["operational_failure"]
    adjudicable = strict_matches + accepted_additional + confirmed_agent_errors
    accepted_adjudicable = strict_matches + accepted_additional

    catalog_calls_by_category: dict[str, int] = defaultdict(int)
    for case in audited:
        catalog_calls_by_category[case["audit_category"]] += int(
            by_id[case["id"]].get("catalog_tool_calls_count") or 0
        )

    summary = {
        "records": len(records),
        "strict_matches": strict_matches,
        "strict_match_rate": strict_matches / len(records),
        "audited_failures": len(audited),
        "categories": dict(categories),
        "layers": dict(layers),
        "confidence": dict(confidence),
        "themes": dict(themes.most_common()),
        "accepted_additional": accepted_additional,
        "indeterminate_benchmark_cases": indeterminate,
        "confirmed_agent_semantic_errors": confirmed_agent_errors,
        "operational_failures": operational_failures,
        "adjudicable_cases": adjudicable,
        "accepted_adjudicable_cases": accepted_adjudicable,
        "accepted_rate_among_adjudicable": accepted_adjudicable / adjudicable,
        "catalog_tool_calls_total": sum(int(record.get("catalog_tool_calls_count") or 0) for record in records),
        "catalog_tool_calls_by_category": dict(catalog_calls_by_category),
        "correction_cases": sum(bool(record.get("correction_attempts")) for record in records),
        "correction_attempts": sum(len(record.get("correction_attempts") or []) for record in records),
        "failure_records_with_warnings": sum(
            bool(by_id[case["id"]].get("generated_sql_validation_warnings")) for case in audited
        ),
        "failure_records_with_valid_sql": sum(
            by_id[case["id"]].get("generated_sql_valid") is True for case in audited
        ),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
