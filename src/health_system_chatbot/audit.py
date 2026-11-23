from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ChatbotConfig
from .text import tokenize


def default_audit_log_path(config: ChatbotConfig) -> Path:
    return config.audit_log_path or config.project_root / "evaluation/chatbot/audit/chat_audit.jsonl"


def append_audit_record(config: ChatbotConfig, record: dict[str, Any]) -> Path:
    path = default_audit_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        **record,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True, default=str))
        f.write("\n")
    return path


# find_related_audit_context runs on every question; scanning only the most
# recent records keeps its cost flat while the append-only log keeps growing.
RELATED_CONTEXT_SCAN_LIMIT = 500


def _tail_lines(path: Path, limit: int, block_size: int = 64 * 1024) -> list[str]:
    with path.open("rb") as f:
        f.seek(0, 2)
        position = f.tell()
        data = b""
        while position > 0 and data.count(b"\n") <= limit:
            read_size = min(block_size, position)
            position -= read_size
            f.seek(position)
            data = f.read(read_size) + data
    lines = data.decode("utf-8", errors="replace").splitlines()
    if position > 0:
        lines = lines[1:]  # the first line read from mid-file may be partial
    return lines[-limit:]


def read_audit_records(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if limit is not None and limit <= 0:
        return []
    lines = (
        _tail_lines(path, limit)
        if limit is not None
        else path.read_text(encoding="utf-8").splitlines()
    )
    records = []
    for line in lines:
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a concurrent append can leave a partial trailing line
    return records


def find_related_audit_context(
    config: ChatbotConfig,
    question: str,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    question_tokens = tokenize(question)
    if not question_tokens:
        return []

    related: list[dict[str, Any]] = []
    recent = read_audit_records(
        default_audit_log_path(config), limit=RELATED_CONTEXT_SCAN_LIMIT
    )
    for record in reversed(recent):
        previous_question = str(record.get("question") or "")
        previous_tokens = tokenize(previous_question)
        overlap = question_tokens & previous_tokens
        if len(overlap) < 2:
            continue

        answer = record.get("answer") if isinstance(record.get("answer"), dict) else {}
        related.append(
            {
                "question": previous_question,
                "answer_status": record.get("answer_status"),
                "result_summary": answer.get("result_summary", ""),
                "caveats": answer.get("caveats", []),
                "sql": answer.get("sql", ""),
            }
        )
        if len(related) >= limit:
            break
    return related


def _trace_path(config: ChatbotConfig) -> Path:
    traces = config.project_root / "evaluation/chatbot/traces"
    traces.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return traces / f"trace_{stamp}.json"


def _write_trace(config: ChatbotConfig, payload: dict[str, Any]) -> None:
    path = _trace_path(config)
    payload["trace_path"] = str(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")


def write_observability_record(
    config: ChatbotConfig,
    trace: dict[str, Any],
    *,
    write_trace: bool,
    write_audit_log: bool,
) -> None:
    if write_trace:
        _write_trace(config, trace)
    if write_audit_log:
        append_audit_record(
            config,
            {
                "event_type": "chat_question",
                "question": trace.get("question"),
                "created_at": trace.get("created_at"),
                "answer_status": trace.get("answer", {}).get("status"),
                "answer": trace.get("answer"),
                "steps": trace.get("steps", []),
                "errors": [
                    step
                    for step in trace.get("steps", [])
                    if step.get("name") in {"validation", "failure"}
                    and step.get("payload", {}).get("errors")
                ],
                "correctness": {
                    "status": "not_evaluated",
                    "reason": "Ad hoc chat questions do not have ground-truth labels by default.",
                },
                "trace_path": trace.get("trace_path"),
            },
        )
