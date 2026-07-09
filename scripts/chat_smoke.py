from __future__ import annotations

from health_system_chatbot.artifacts import load_stage1_context
from health_system_chatbot.config import load_config
from health_system_chatbot.workflow import run_chat


QUESTIONS = [
    "Quantas internacoes existem na tabela principal?",
    "Qual e o valor total aprovado registrado em VAL_TOT?",
    "Quantas internacoes ocorreram por ano de entrada?",
    "Qual foi a taxa bruta de mortalidade hospitalar por ano?",
    "Qual foi o custo por local?",
    "Quantos pacientes unicos existem na base?",
]


def main() -> int:
    config = load_config()
    ctx = load_stage1_context(config.project_root, db_path=config.db_path)
    for question in QUESTIONS:
        answer = run_chat(
            question,
            config=config,
            stage1_context=ctx,
            show_sql=True,
            allow_llm=True,
            write_trace=False,
        )
        print(f"\n## {question}\n{answer.status}\n{answer.answer_pt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
