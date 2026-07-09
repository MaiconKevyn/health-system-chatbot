from evaluation.chatbot.ablation.reports import build_failure_sets, write_ablation_outputs
from evaluation.chatbot.eval_core.sql_case import build_empty_record
from health_system_chatbot.models import GroundTruthItem


def _record(item, variant, match):
    record = build_empty_record(item, variant=variant, strategy="fake")
    record["generated_sql"] = "SELECT 1"
    record["generated_sql_valid"] = True
    record["generated_execution_status"] = "passed"
    record["ground_truth_execution_status"] = "passed"
    record["result_match"] = match
    record["shape_match"] = match
    record["error_category"] = None if match else "value_mismatch"
    return record


def test_build_failure_sets_detects_agent_and_baseline_wins():
    item = GroundTruthItem(id="T001", question_pt="Pergunta", sql="SELECT 1")
    records = [
        _record(item, "full_agent", False),
        _record(item, "openai_raw_retrieved_schema", True),
        _record(item, "no_catalog_tools", False),
    ]

    failures = build_failure_sets(records)

    assert len(failures["baseline_wins"]) == 1
    assert len(failures["regressions_vs_full_agent"]) == 0


def test_write_ablation_outputs_creates_expected_files(tmp_path):
    item = GroundTruthItem(id="T001", question_pt="Pergunta", sql="SELECT 1")
    records = [_record(item, "full_agent", True)]

    payload = write_ablation_outputs(
        run_dir=tmp_path,
        run_id="test_run",
        run_config={"dataset": "fake.jsonl", "variants": ["full_agent"]},
        records=records,
    )

    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "summary.csv").exists()
    assert (tmp_path / "analysis.md").exists()
    assert (tmp_path / "trace.jsonl").exists()
    assert (tmp_path / "variants/full_agent/results.json").exists()
    assert payload["variant_ranking"][0]["variant"] == "full_agent"
