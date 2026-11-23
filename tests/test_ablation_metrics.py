from evaluation.chatbot.ablation.metrics import bootstrap_ci_by_template


def test_bootstrap_resamples_template_families_and_excludes_not_scorable():
    records = [
        {"id": "a1", "template_family": "a", "semantic_match": True, "benchmark_status": "scored"},
        {"id": "a2", "template_family": "a", "semantic_match": True, "benchmark_status": "scored"},
        {"id": "b1", "template_family": "b", "semantic_match": False, "benchmark_status": "scored"},
        {"id": "x", "template_family": "x", "semantic_match": False, "benchmark_status": "not_scorable"},
    ]

    interval = bootstrap_ci_by_template(records, metric="semantic_match", samples=200, seed=7)

    assert interval is not None
    assert interval["template_families"] == 2
    assert interval["samples"] == 200
    assert 0 <= interval["lower"] <= interval["upper"] <= 1
