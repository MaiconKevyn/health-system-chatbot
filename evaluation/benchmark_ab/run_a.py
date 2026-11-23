"""Adapter for health-system-chatbot. Run with A's venv, cwd = snapshot A.

    cd <snapshot>/A && <A venv>/bin/python <this file> <gt.jsonl> <out.jsonl> --engine legacy|product [--workers N] [--ids ...]

--engine legacy   system "A": the historical Pydantic AI pipeline
                  (`workflow.run_chat`: SQL planning, validation, correction,
                  execution, chart planning, answer synthesis).
--engine product  system "P": what the product API/CLI serve today
                  (`chat.run_chat` with CHATBOT_CHAT_ENGINE=sus, the SUS engine
                  integrated into this repo).

Each worker process loads config/context once. The audit log points to an empty
file and nothing is written to it, so no question sees earlier answers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

_STATE: dict = {}
SYSTEM = {"legacy": "A", "product": "P"}


def _init(empty_audit: str, engine: str, effort: str) -> None:
    os.environ["CHATBOT_AUDIT_LOG_PATH"] = empty_audit
    os.environ["CHATBOT_LLM_MODEL"] = "gpt-6-luna"
    os.environ["CHATBOT_LLM_REASONING_EFFORT"] = effort
    os.environ["CHATBOT_CHAT_ENGINE"] = "sus" if engine == "product" else "legacy"
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    sys.path.insert(0, str(Path.cwd() / "src"))
    import warnings

    warnings.filterwarnings("ignore")
    from health_system_chatbot.artifacts import load_stage1_context
    from health_system_chatbot.config import load_config

    config = load_config(Path.cwd())
    _STATE["config"] = config
    try:
        _STATE["ctx"] = load_stage1_context(config.project_root, db_path=config.db_path)
    except TypeError:  # older signature
        _STATE["ctx"] = load_stage1_context(config.project_root)
    if engine == "product":
        from health_system_chatbot.chat import run_chat
    else:
        from health_system_chatbot.workflow import run_chat
    _STATE["run_chat"] = run_chat
    _STATE["system"] = SYSTEM[engine]


def _answer(item: dict) -> dict:
    t = time.time()
    out = {"id": item["id"], "question": item["question"], "system": _STATE["system"]}
    try:
        ans = _STATE["run_chat"](
            item["question"],
            config=_STATE["config"],
            stage1_context=_STATE["ctx"],
            show_sql=True,
            show_debug=True,
            allow_llm=True,
            write_trace=False,
            write_audit_log=False,
        )
        dev = ans.developer_context or {}
        ev = ans.evidence or {}
        out.update(
            status=ans.status,
            answer=ans.answer_pt,
            sql=ans.sql or "",
            caveats=ans.caveats,
            refused=ans.status != "answered",
            meta={
                "engine": _STATE["config"].active_chat_engine if hasattr(_STATE["config"], "active_chat_engine") else "legacy",
                "plan_source": ev.get("plan_source"),
                "answer_source": dev.get("answer_source") or ev.get("answer_source"),
                "natural_answer_warning": dev.get("natural_answer_warning"),
                "chart_rendered": ev.get("chart_rendered"),
                "row_count": ev.get("row_count"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        out.update(status="error", answer="", sql="", refused=True,
                   error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()[-2000:])
    out["latency_s"] = round(time.time() - t, 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("gt")
    ap.add_argument("out")
    ap.add_argument("--engine", choices=sorted(SYSTEM), required=True)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--ids", nargs="*")
    args = ap.parse_args()

    items = [json.loads(line) for line in open(args.gt, encoding="utf-8")]
    if args.ids:
        items = [i for i in items if i["id"] in set(args.ids)]
    out_path = Path(args.out)
    done = set()
    if out_path.exists():
        done = {json.loads(line)["id"] for line in out_path.open(encoding="utf-8") if line.strip()}
    todo = [i for i in items if i["id"] not in done]
    empty_audit = str(out_path.with_name(f"empty_audit_{SYSTEM[args.engine]}.jsonl"))
    Path(empty_audit).write_text("", encoding="utf-8")
    tag = SYSTEM[args.engine]
    print(f"{tag}: {len(todo)} to run ({len(done)} already done)", flush=True)

    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init,
                             initargs=(empty_audit, args.engine, args.effort)) as ex, \
            out_path.open("a", encoding="utf-8") as fh:
        futures = {ex.submit(_answer, {"id": i["id"], "question": i["question"]}): i["id"] for i in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            print(f"{tag} [{n}/{len(todo)}] {rec['id']} {rec['status']} {rec['latency_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
