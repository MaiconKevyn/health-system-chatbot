from pathlib import Path

from evaluation.chatbot.evaluate_extraction_accuracy import load_dataset, summarize


ROOT = Path(__file__).resolve().parents[1]


def test_hard_benchmark_marks_ambiguous_cases_not_scorable():
    items = load_dataset(ROOT / "evaluation/ground_truth/ground_truth_hard_73.jsonl")
    by_id = {item.id: item for item in items}

    assert by_id["GT044"].benchmark_status == "not_scorable"
    assert by_id["GT205"].benchmark_status == "not_scorable"
    assert by_id["GT049"].benchmark_status == "not_scorable"
    assert by_id["GT049"].required_output_concepts == [
        "admissions",
        "deaths",
        "mortality_rate",
    ]


def test_summary_excludes_not_scorable_cases_from_primary_rate():
    records = [
        {
            "benchmark_status": "scored",
            "intent_status": "answerable",
            "generated_sql": "SELECT 1",
            "generated_sql_valid": True,
            "generated_execution_status": "passed",
            "ground_truth_execution_status": "passed",
            "expected_truncated": False,
            "actual_truncated": False,
            "result_match": True,
            "semantic_match": True,
            "presentation_match": False,
            "alias_only_difference": True,
            "type_only_difference": False,
            "order_only_mismatch": False,
            "semantic_label_equivalence": False,
            "correction_attempts": [],
            "candidate_count": 1,
            "latency_seconds": 0.1,
            "error_category": None,
        },
        {
            "benchmark_status": "not_scorable",
            "intent_status": "answerable",
            "generated_sql": "SELECT 2",
            "generated_sql_valid": True,
            "generated_execution_status": "passed",
            "ground_truth_execution_status": "passed",
            "expected_truncated": False,
            "actual_truncated": False,
            "result_match": False,
            "semantic_match": False,
            "presentation_match": False,
            "alias_only_difference": False,
            "type_only_difference": False,
            "order_only_mismatch": False,
            "semantic_label_equivalence": False,
            "correction_attempts": [],
            "candidate_count": 1,
            "latency_seconds": 0.1,
            "error_category": "benchmark_ambiguous",
        },
    ]

    result = summarize(records)

    assert result["total"] == 2
    assert result["scored_total"] == 1
    assert result["not_scorable_count"] == 1
    assert result["result_match_rate"] == 1.0
    assert result["semantic_match_rate"] == 1.0
    assert result["presentation_match_rate"] == 0.0
