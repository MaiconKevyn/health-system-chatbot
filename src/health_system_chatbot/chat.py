"""Product entry point shared by the HTTP chat and the interactive/batch CLI."""

from datetime import UTC, datetime

from .audit import write_observability_record
from .config import ChatbotConfig
from .models import ChatbotAnswer, Stage1Context


def run_chat(
    question: str,
    *,
    config: ChatbotConfig,
    stage1_context: Stage1Context,
    show_sql: bool = False,
    show_debug: bool = False,
    allow_llm: bool = True,
    write_trace: bool = True,
    write_audit_log: bool = True,
) -> ChatbotAnswer:
    if not allow_llm or config.active_chat_engine == "legacy":
        from .workflow import run_chat as run_legacy_chat

        return run_legacy_chat(
            question,
            config=config,
            stage1_context=stage1_context,
            allow_llm=allow_llm,
            show_sql=show_sql,
            show_debug=show_debug,
            write_trace=write_trace,
            write_audit_log=write_audit_log,
        )

    from .sus.engine import ask

    trace = {
        "question": question,
        "created_at": datetime.now(UTC).isoformat(),
        "steps": [],
    }
    answer = ask(
        question,
        config,
        stage1_context,
        show_sql=show_sql,
        show_debug=show_debug,
        steps=trace["steps"],
    )
    trace["answer"] = answer.model_dump()
    write_observability_record(
        config, trace, write_trace=write_trace, write_audit_log=write_audit_log
    )
    return answer
