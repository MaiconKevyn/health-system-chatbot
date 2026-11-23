import json

from health_system_chatbot.audit import append_audit_record, read_audit_records
from health_system_chatbot.config import ChatbotConfig


def test_append_audit_record_writes_jsonl(tmp_path):
    config = ChatbotConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.duckdb",
        openai_api_key=None,
        audit_log_path=tmp_path / "audit/chat_audit.jsonl",
    )

    path = append_audit_record(config, {"question": "q1", "answer_status": "answered"})
    append_audit_record(config, {"question": "q2", "answer_status": "failed"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["question"] == "q1"

    records = read_audit_records(path, limit=1)
    assert len(records) == 1
    assert records[0]["question"] == "q2"


def test_read_audit_records_tail_reads_only_the_most_recent_records(tmp_path):
    path = tmp_path / "chat_audit.jsonl"
    padding = "x" * 300
    path.write_text(
        "".join(json.dumps({"question": f"q{i}", "pad": padding}) + "\n" for i in range(2000))
        + '{"question": "partial',
        encoding="utf-8",
    )

    records = read_audit_records(path, limit=3)

    assert [record["question"] for record in records] == ["q1998", "q1999"]
    assert len(read_audit_records(path, limit=10)) == 9
    assert read_audit_records(path, limit=0) == []
