from health_system_chatbot.evaluation import summarize_records
from health_system_chatbot.models import EvaluationRecord


def test_summarize_records_computes_rates():
    records = [
        EvaluationRecord(
            id="Q1",
            question_pt="q",
            difficulty="L1",
            status="answered",
            intent_status="answerable",
            sql_valid=True,
            executed=True,
            result_match=True,
            latency_seconds=0.1,
        ),
        EvaluationRecord(
            id="Q2",
            question_pt="q",
            difficulty="L2",
            status="failed",
            intent_status="answerable",
            sql_valid=False,
            executed=False,
            result_match=False,
            latency_seconds=0.2,
            error_category="sql_validation_error",
            errors=["bad"],
        ),
    ]

    summary = summarize_records(records)

    assert summary["total"] == 2
    assert summary["sql_valid_rate"] == 0.5
    assert summary["sql_execution_rate"] == 0.5
    assert summary["result_match_rate"] == 0.5
    assert summary["failure_by_difficulty"] == {"L2": 1}
    assert summary["failure_by_category"] == {"sql_validation_error": 1}
    assert len(summary["failures"]) == 1
