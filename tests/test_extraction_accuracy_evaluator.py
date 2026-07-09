from __future__ import annotations

import json
from decimal import Decimal

from evaluation.chatbot.evaluate_extraction_accuracy import (
    append_trace_record,
    build_run_id,
    build_parser,
    canonicalize_result,
    compare_results,
    format_progress_done,
    format_progress_start,
    initialize_trace,
    resolve_run_paths,
    summarize,
    write_failure_examples,
    write_summary_csv,
)


def test_alias_only_difference_is_match():
    result = compare_results(
        ["total_internacoes"],
        [(10,)],
        ["total"],
        [(10,)],
        mode="scalar",
    )

    assert result.result_match is True
    assert result.alias_only_difference is True
    assert result.error_category is None


def test_value_mismatch_is_not_match():
    result = compare_results(
        ["total"],
        [(10,)],
        ["total"],
        [(11,)],
        mode="scalar",
    )

    assert result.result_match is False
    assert result.error_category == "value_mismatch"


def test_shape_mismatch_is_not_match():
    result = compare_results(
        ["uf", "total"],
        [("MA", 10)],
        ["uf"],
        [("MA",)],
        mode="ordered",
    )

    assert result.result_match is False
    assert result.shape_match is False
    assert result.error_category == "shape_mismatch"


def test_unordered_distribution_matches_same_rows_different_order():
    result = compare_results(
        ["uf", "total"],
        [("MA", 1), ("RS", 2)],
        ["uf", "total"],
        [("RS", 2), ("MA", 1)],
        mode="unordered",
    )

    assert result.result_match is True
    assert result.order_only_mismatch is False


def test_ordered_mode_reports_order_only_mismatch():
    result = compare_results(
        ["uf", "total"],
        [("MA", 1), ("RS", 2)],
        ["uf", "total"],
        [("RS", 2), ("MA", 1)],
        mode="ordered",
    )

    assert result.result_match is False
    assert result.order_only_mismatch is True
    assert result.error_category == "order_only_mismatch"


def test_numeric_tolerance_accepts_small_decimal_difference():
    result = compare_results(
        ["taxa"],
        [(Decimal("10.0000001"),)],
        ["taxa"],
        [(10.0000002,)],
        mode="scalar",
        numeric_tolerance=1e-6,
    )

    assert result.result_match is True


def test_numeric_text_matches_number_as_type_only_difference():
    result = compare_results(
        ["ano", "total"],
        [(2000, 9)],
        ["ano_entrada", "total"],
        [("2000", 9)],
        mode="ordered",
    )

    assert result.result_match is True
    assert result.alias_only_difference is True
    assert result.type_only_difference is True


def test_canonicalize_result_ignores_column_names_and_normalizes_decimal():
    expected = canonicalize_result(["alias_a"], [(Decimal("10.50"),)])
    actual = canonicalize_result(["alias_b"], [(10.5,)])

    assert expected == actual


def test_summary_is_json_serializable_and_counts_categories():
    records = [
        {
            "intent_status": "answerable",
            "generated_sql": "SELECT 1",
            "generated_sql_valid": True,
            "generated_execution_status": "passed",
            "ground_truth_execution_status": "passed",
            "expected_truncated": False,
            "actual_truncated": False,
            "result_match": True,
            "alias_only_difference": True,
            "type_only_difference": False,
            "order_only_mismatch": False,
            "error_category": None,
            "correction_attempts": [],
            "candidate_count": 1,
            "latency_seconds": 0.1,
        },
        {
            "intent_status": "answerable",
            "generated_sql": "SELECT 2",
            "generated_sql_valid": True,
            "generated_execution_status": "passed",
            "ground_truth_execution_status": "passed",
            "expected_truncated": False,
            "actual_truncated": False,
            "result_match": False,
            "alias_only_difference": False,
            "type_only_difference": False,
            "order_only_mismatch": False,
            "error_category": "value_mismatch",
            "difficulty": "L1",
            "correction_attempts": [{"attempt": 1, "success": True}],
            "correction_success": True,
            "candidate_count": 2,
            "candidate_selection_correct": False,
            "latency_seconds": 0.2,
        },
    ]

    payload = summarize(records)

    assert payload["total"] == 2
    assert payload["result_value_match_rate"] == 0.5
    assert payload["alias_only_difference_count"] == 1
    assert payload["type_only_difference_count"] == 0
    assert payload["value_mismatch_count"] == 1
    assert payload["correction_success_rate"] == 1.0
    assert payload["candidate_selection_accuracy"] == 0.0
    assert payload["failures_by_difficulty"] == {"L1": 1}
    json.dumps(payload)


def test_run_paths_create_per_run_result_folder(tmp_path):
    run_id = build_run_id("Extraction Run 001")
    paths = resolve_run_paths(
        tmp_path,
        results_root="evaluation/chatbot/results",
        run_id=run_id,
    )

    assert run_id == "Extraction_Run_001"
    assert paths.run_dir == tmp_path / "evaluation/chatbot/results/Extraction_Run_001"
    assert paths.output == paths.run_dir / "results.json"
    assert paths.analysis_output == paths.run_dir / "analysis.md"
    assert paths.trace_output == paths.run_dir / "trace.jsonl"
    assert paths.failure_examples_output == paths.run_dir / "failure_examples.jsonl"
    assert paths.summary_csv_output == paths.run_dir / "summary.csv"


def test_failure_examples_and_summary_csv_are_written(tmp_path):
    failure_path = tmp_path / "failure_examples.jsonl"
    summary_path = tmp_path / "summary.csv"
    records = [
        {
            "id": "Q1",
            "difficulty": "L1",
            "question_pt": "q",
            "error_category": "value_mismatch",
            "error_message": "bad value",
            "generated_sql": "SELECT 1",
            "ground_truth_sql": "SELECT 2",
            "generated_sql_validation_errors": [],
            "generated_sql_validation_warnings": [],
            "generated_execution_status": "passed",
            "ground_truth_execution_status": "passed",
            "expected_preview_values": [[2]],
            "actual_preview_values": [[1]],
            "retrieved_tables": ["internacoes"],
            "business_metrics": ["total_internacoes"],
            "selected_candidate_id": "candidate_1",
            "correction_attempts": [],
        },
        {"id": "Q2", "error_category": None},
    ]

    write_failure_examples(records, failure_path)
    write_summary_csv({"total": 2, "error_category_counts": {"value_mismatch": 1}}, summary_path)

    lines = failure_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["next_action"]
    assert "metric,value" in summary_path.read_text(encoding="utf-8")


def test_trace_record_is_appended_incrementally(tmp_path):
    path = initialize_trace(tmp_path / "trace.jsonl")

    append_trace_record({"id": "Q1", "result_match": True}, path)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    append_trace_record({"id": "Q2", "result_match": False}, path)
    lines = path.read_text(encoding="utf-8").splitlines()

    assert [json.loads(line)["id"] for line in lines] == ["Q1", "Q2"]


def test_progress_messages_include_item_status_and_elapsed_time():
    assert format_progress_start(1, 100, "SIHRD5_Q001") == (
        "[1/100] SIHRD5_Q001 running..."
    )

    message = format_progress_done(
        1,
        100,
        {
            "id": "SIHRD5_Q001",
            "result_match": True,
            "generated_execution_status": "passed",
            "ground_truth_execution_status": "passed",
            "error_category": None,
            "latency_seconds": 1.234,
        },
    )

    assert message == (
        "[1/100] SIHRD5_Q001 done match=True generated=passed "
        "ground_truth=passed error=none elapsed=1.23s"
    )


def test_parser_supports_quiet_mode_for_progress_logs():
    args = build_parser().parse_args(["--quiet"])

    assert args.quiet is True
