from health_system_chatbot.models import QuestionContract
from health_system_chatbot.result_probes import probe_result_contract


def _contract() -> QuestionContract:
    return QuestionContract(cumulative_threshold_percent=80.0)


def test_cumulative_probe_requires_crossing_row():
    report = probe_result_contract(
        contract=_contract(),
        columns=["categoria", "percentual_acumulado"],
        rows=[["a", 60.0], ["b", 79.0]],
    )

    assert report.errors
    assert report.findings[0]["crossing_index"] is None


def test_cumulative_probe_accepts_minimal_prefix_in_fraction_scale():
    report = probe_result_contract(
        contract=_contract(),
        columns=["categoria", "cobertura_acumulada"],
        rows=[["a", 0.6], ["b", 0.82]],
    )

    assert report.errors == []


def test_cumulative_probe_rejects_rows_after_crossing():
    report = probe_result_contract(
        contract=_contract(),
        columns=["categoria", "percentual_acumulado"],
        rows=[["a", 60.0], ["b", 82.0], ["c", 90.0]],
    )

    assert any("after" in error for error in report.errors)
