import argparse
import json

from evaluation.chatbot.run_ablation import apply_suite_args, build_run_id


def test_build_run_id_sanitizes_value():
    assert build_run_id(" my run/id ") == "my_run_id"


def test_apply_suite_args_fills_missing_values(tmp_path):
    suite_file = tmp_path / "suites.json"
    suite_file.write_text(
        json.dumps(
            {
                "smoke": {
                    "dataset": "dataset.jsonl",
                    "ids": ["A", "B"],
                    "limit": 2,
                    "variants": ["full_agent", "no_catalog_tools"],
                }
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        suite="smoke",
        suite_file=str(suite_file.relative_to(tmp_path)),
        dataset=None,
        ids=None,
        limit=None,
        variants=None,
    )

    updated = apply_suite_args(args, tmp_path)

    assert updated.dataset == "dataset.jsonl"
    assert updated.ids == "A,B"
    assert updated.limit == 2
    assert updated.variants == "full_agent,no_catalog_tools"
