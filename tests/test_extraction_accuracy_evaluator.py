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
    assert result.contained_in_actual is False


def test_extra_actual_columns_match_when_expected_projection_is_contained():
    result = compare_results(
        ["municipio", "total_internacoes", "total_mortes", "taxa_mortalidade"],
        [("A", 100, 10, 10.0), ("B", 200, 20, 10.0)],
        ["municipio", "uf", "internacoes", "obitos", "taxa_mortalidade"],
        [("A", "RS", 100, 10, 10.0), ("B", "RS", 200, 20, 10.0)],
        mode="ordered",
    )

    assert result.result_match is True
    assert result.shape_match is False
    assert result.contained_in_actual is True
    assert result.error_category is None


def test_extra_ordered_rows_match_when_expected_prefix_is_contained():
    result = compare_results(
        ["municipio", "taxa"],
        [("A", 10.0)],
        ["municipio", "taxa"],
        [("A", 10.0), ("B", 9.0)],
        mode="ordered",
    )

    assert result.result_match is True
    assert result.shape_match is False
    assert result.contained_in_actual is True


def test_extra_actual_columns_match_when_expected_rows_are_unordered_contained():
    result = compare_results(
        ["nome"],
        [("Bage",), ("Sao Leopoldo",)],
        ["municipio", "uf", "internacoes"],
        [("Sao Leopoldo", "RS", 184103), ("Bage", "RS", 120196)],
        mode="ordered",
    )

    assert result.result_match is True
    assert result.shape_match is False
    assert result.order_only_mismatch is True
    assert result.contained_in_actual is True


def test_generated_projection_matches_when_contained_in_ground_truth():
    result = compare_results(
        ["quartil", "total", "minimo", "maximo", "media"],
        [(1, 10, 1, 100, 50)],
        ["quartil", "total", "minimo", "maximo"],
        [(1, 10, 1, 100)],
        mode="ordered",
    )

    assert result.result_match is True
    assert result.shape_match is False
    assert result.contained_in_expected is True
    assert result.error_category is None


def test_missing_value_still_remains_shape_mismatch():
    result = compare_results(
        ["quartil", "total", "minimo", "maximo", "media"],
        [(1, 10, 1, 100, 50)],
        ["quartil", "total", "minimo", "maximo"],
        [(1, 10, 1, 101)],
        mode="ordered",
    )

    assert result.result_match is False
    assert result.shape_match is False
    assert result.contained_in_expected is False
    assert result.error_category == "shape_mismatch"


def test_text_values_ignore_case_and_accents():
    result = compare_results(
        ["carater"],
        [("urgencia",)],
        ["carater"],
        [("Urgência",)],
        mode="scalar",
    )

    assert result.result_match is True


def test_text_values_accept_portuguese_adjective_gender_variants():
    result = compare_results(
        ["faixa_etaria", "carater", "internacoes", "mortes", "taxa"],
        [
            ("<18", "eletiva", 3_928_508, 21_571, 0.55),
            ("<18", "urgencia", 24_252_648, 308_249, 1.27),
        ],
        ["faixa_etaria", "carater", "internacoes", "mortes", "taxa"],
        [
            ("<18", "Eletivo", 3_928_508, 21_571, 0.55),
            ("<18", "Urgência", 24_252_648, 308_249, 1.27),
        ],
        mode="unordered",
    )

    assert result.result_match is True
    assert result.semantic_label_equivalence is True


def test_text_values_do_not_equate_unrelated_or_arbitrary_labels():
    unrelated = compare_results(
        ["carater", "total"],
        [("eletiva", 10)],
        ["carater", "total"],
        [("urgencia", 10)],
        mode="unordered",
    )
    arbitrary_gendered_nouns = compare_results(
        ["categoria", "total"],
        [("banco", 10)],
        ["categoria", "total"],
        [("banca", 10)],
        mode="unordered",
    )

    assert unrelated.result_match is False
    assert arbitrary_gendered_nouns.result_match is False


def test_numeric_values_match_when_one_side_is_rounded():
    result = compare_results(
        ["taxa"],
        [(7.41,)],
        ["taxa"],
        [(7.4054,)],
        mode="scalar",
    )

    assert result.result_match is True


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


def test_ordered_mode_accepts_reordering_inside_tied_metric_block():
    result = compare_results(
        ["ano", "capitulo", "total", "percentual"],
        [(2020, "II. Neoplasias", 573971, 6.96), (2020, "X. Respiratorias", 574236, 6.96)],
        ["ano", "capitulo", "total", "percentual"],
        [(2020, "X. Respiratorias", 574236, 6.96), (2020, "II. Neoplasias", 573971, 6.96)],
        mode="ordered",
    )

    assert result.result_match is True
    assert result.order_only_mismatch is True
    assert result.error_category is None


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
            "semantic_label_equivalence": True,
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
            "catalog_candidates_count": 2,
            "catalog_tool_calls_count": 1,
            "catalog_decisions_count": 1,
            "latency_seconds": 0.2,
        },
    ]

    payload = summarize(records)

    assert payload["total"] == 2
    assert payload["result_value_match_rate"] == 0.5
    assert payload["result_match_rate"] == 0.5
    assert payload["alias_only_difference_count"] == 1
    assert payload["type_only_difference_count"] == 0
    assert payload["semantic_label_equivalence_count"] == 1
    assert payload["value_mismatch_count"] == 1
    assert payload["correction_success_rate"] == 1.0
    assert payload["candidate_selection_accuracy"] == 0.0
    assert payload["catalog_candidates_rate"] == 0.5
    assert payload["catalog_tool_call_rate"] == 0.5
    assert payload["catalog_decision_rate"] == 0.5
    assert payload["catalog_tool_call_count"] == 1
    assert payload["catalog_decision_count"] == 1
    assert payload["failures_by_difficulty"] == {"L1": 1}
    json.dumps(payload)


def test_summary_counts_non_executable_sql_as_end_to_end_failure():
    common = {
        "intent_status": "answerable",
        "ground_truth_execution_status": "passed",
        "expected_truncated": False,
        "actual_truncated": False,
        "alias_only_difference": False,
        "type_only_difference": False,
        "order_only_mismatch": False,
        "correction_attempts": [],
        "candidate_count": 1,
        "latency_seconds": 0.1,
    }
    records = [
        {
            **common,
            "generated_sql": "SELECT 1",
            "generated_sql_valid": True,
            "generated_execution_status": "passed",
            "result_match": True,
            "error_category": None,
        },
        {
            **common,
            "generated_sql": "SELECT invalid",
            "generated_sql_valid": False,
            "generated_execution_status": "skipped",
            "result_match": False,
            "error_category": "invalid_sql",
        },
    ]

    payload = summarize(records)

    assert payload["result_match_rate"] == 0.5
    assert payload["comparable_result_match_rate"] == 1.0
    assert payload["result_value_match_rate"] == 1.0


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
    args = build_parser().parse_args(
        ["--quiet", "--catalog-tools", "off", "--catalog-retrieval-mode", "lexical"]
    )

    assert args.quiet is True
    assert args.catalog_tools == "off"
    assert args.catalog_retrieval_mode == "lexical"
