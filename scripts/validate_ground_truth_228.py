from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from health_system_chatbot.config import load_config


ROOT_INPUT = "ground_truth_228.json"
OUTPUT_JSON = "evaluation/ground_truth/ground_truth_228_validated.json"
OUTPUT_JSONL = "evaluation/ground_truth/ground_truth_228_validated.jsonl"
REPORT_JSON = "evaluation/ground_truth/ground_truth_228_validation_report.json"
REPORT_MD = "evaluation/ground_truth/ground_truth_228_validation_report.md"
EVIDENCE_DIR = "evaluation/ground_truth/query_results_228"


OVERRIDES: dict[str, dict[str, Any]] = {
    "GT021": {
        "question": "Quais são os 5 procedimentos principais mais registrados nas internações?",
        "query": (
            'SELECT p."PROC_REA", p."NOME_PROC" AS procedimento, COUNT(*) AS total '
            'FROM internacoes i JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'GROUP BY p."PROC_REA", p."NOME_PROC" ORDER BY total DESC LIMIT 5'
        ),
        "tables": ["internacoes", "procedimentos"],
        "adjustment_reason": "internacao_procedimento nao existe no DuckDB atual; usar procedimento principal em internacoes.PROC_REA.",
    },
    "GT024": {
        "question": "Quais CNES têm mais de 1000 internações registradas?",
        "query": (
            'SELECT i."CNES", COUNT(i."N_AIH") AS total_internacoes '
            'FROM internacoes i WHERE i."CNES" IS NOT NULL '
            'GROUP BY i."CNES" HAVING COUNT(i."N_AIH") > 1000 '
            'ORDER BY total_internacoes DESC'
        ),
        "tables": ["internacoes"],
        "adjustment_reason": "hospital esta vazia; responder por CNES registrado em internacoes.",
    },
    "GT068": {
        "question": "Quais são os 10 procedimentos principais mais comuns nas internações?",
        "query": (
            'SELECT p."PROC_REA", p."NOME_PROC", COUNT(*) AS total_procedimentos '
            'FROM internacoes i JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'GROUP BY p."PROC_REA", p."NOME_PROC" ORDER BY total_procedimentos DESC LIMIT 10'
        ),
        "tables": ["internacoes", "procedimentos"],
        "adjustment_reason": "internacao_procedimento/id_atendimento nao existem; usar internacoes.PROC_REA.",
    },
    "GT076": {
        "question": "Quais são os 10 municípios de residência com mais internações?",
        "query": (
            'SELECT m."NO_MUNICIPIO" AS municipio, COUNT(i."N_AIH") AS total_internacoes '
            'FROM internacoes i JOIN municipios m ON i."MUNIC_RES" = m."CO_MUNICIPIO_6D" '
            'GROUP BY m."NO_MUNICIPIO" ORDER BY total_internacoes DESC LIMIT 10'
        ),
        "tables": ["internacoes", "municipios"],
        "adjustment_reason": "municipio do hospital depende da tabela hospital, vazia no banco atual; usar municipio de residencia.",
    },
    "GT079": {
        "question": "Quais são os 10 procedimentos principais mais comuns entre internações de residentes no RS?",
        "query": (
            'SELECT p."PROC_REA", p."NOME_PROC" AS procedimento, COUNT(*) AS total_procedimentos '
            'FROM internacoes i '
            'JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'JOIN municipios m ON i."MUNIC_RES" = m."CO_MUNICIPIO_6D" '
            "WHERE m.\"SG_UF\" = 'RS' "
            'GROUP BY p."PROC_REA", p."NOME_PROC" ORDER BY total_procedimentos DESC LIMIT 10'
        ),
        "tables": ["internacoes", "procedimentos", "municipios"],
        "adjustment_reason": "internacao_procedimento e municipio do hospital indisponiveis; usar procedimento principal e residencia.",
    },
    "GT081": {
        "question": "Quais são os 5 procedimentos principais mais registrados para cada sexo?",
        "query": (
            'SELECT sexo, "PROC_REA", "NOME_PROC", total FROM ('
            'SELECT s."DESCRICAO" AS sexo, p."PROC_REA", p."NOME_PROC", COUNT(*) AS total, '
            'ROW_NUMBER() OVER (PARTITION BY s."DESCRICAO" ORDER BY COUNT(*) DESC) AS rn '
            'FROM internacoes i JOIN sexo s ON i."SEXO" = s."SEXO" '
            'JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'GROUP BY s."DESCRICAO", p."PROC_REA", p."NOME_PROC"'
            ') sub WHERE rn <= 5 ORDER BY sexo, rn'
        ),
        "tables": ["internacoes", "sexo", "procedimentos"],
        "adjustment_reason": "usar procedimento principal e dimensao sexo em vez de CASE manual e tabela inexistente.",
    },
    "GT084": {
        "question": "Quais são os 3 procedimentos principais mais comuns entre internações que resultaram em óbito para cada faixa etária?",
        "query": (
            'SELECT faixa_etaria, "PROC_REA", "NOME_PROC", total FROM ('
            'SELECT CASE WHEN i."IDADE" < 18 THEN \'Menor de 18\' '
            'WHEN i."IDADE" BETWEEN 18 AND 64 THEN \'18 a 64\' ELSE \'65 ou mais\' END AS faixa_etaria, '
            'p."PROC_REA", p."NOME_PROC", COUNT(*) AS total, '
            'ROW_NUMBER() OVER (PARTITION BY CASE WHEN i."IDADE" < 18 THEN \'Menor de 18\' '
            'WHEN i."IDADE" BETWEEN 18 AND 64 THEN \'18 a 64\' ELSE \'65 ou mais\' END ORDER BY COUNT(*) DESC) AS rn '
            'FROM internacoes i JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'WHERE i."MORTE" = true GROUP BY faixa_etaria, p."PROC_REA", p."NOME_PROC"'
            ') sub WHERE rn <= 3 ORDER BY faixa_etaria, rn'
        ),
        "tables": ["internacoes", "procedimentos"],
        "adjustment_reason": "usar procedimento principal em internacoes.PROC_REA.",
    },
    "GT086": {
        "question": "Quais são os 3 CNES com maior custo médio de UTI entre internações de residentes nos estados MA e RS?",
        "query": (
            'SELECT estado, "CNES", ROUND(custo_medio_uti, 2) AS custo_medio_uti FROM ('
            'SELECT mu."SG_UF" AS estado, i."CNES", AVG(i."VAL_UTI") AS custo_medio_uti, '
            'ROW_NUMBER() OVER (PARTITION BY mu."SG_UF" ORDER BY AVG(i."VAL_UTI") DESC) AS rn '
            'FROM internacoes i JOIN municipios mu ON i."MUNIC_RES" = mu."CO_MUNICIPIO_6D" '
            'WHERE i."VAL_UTI" > 0 AND mu."SG_UF" IN (\'MA\', \'RS\') '
            'GROUP BY mu."SG_UF", i."CNES" HAVING COUNT(*) > 100'
            ') sub WHERE rn <= 3 ORDER BY estado, rn'
        ),
        "tables": ["internacoes", "municipios"],
        "adjustment_reason": "estado do hospital indisponivel; usar UF de residencia e CNES.",
    },
    "GT089": {
        "question": "Quais são os 10 CNES com maior taxa de mortalidade obstétrica (com mais de 500 internações obstétricas)?",
        "query": (
            'SELECT i."CNES", COUNT(*) AS total_obstetricos, '
            'SUM(CASE WHEN i."MORTE" = true THEN 1 ELSE 0 END) AS total_mortes, '
            'ROUND(SUM(CASE WHEN i."MORTE" = true THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS pct_mortalidade '
            'FROM internacoes i WHERE i."ESPEC" = 2 AND i."CNES" IS NOT NULL '
            'GROUP BY i."CNES" HAVING COUNT(*) > 500 ORDER BY pct_mortalidade DESC LIMIT 10'
        ),
        "tables": ["internacoes"],
        "adjustment_reason": "hospital esta vazia; agrupar por CNES da internacao.",
    },
    "GT091": {
        "question": "Quais são os 5 CNES mais eficientes em custo por dia de internação (com mais de 1000 internações)?",
        "query": (
            'SELECT i."CNES", ROUND(SUM(i."VAL_TOT") / NULLIF(SUM(i."DIAS_PERM"), 0), 2) AS custo_por_dia '
            'FROM internacoes i WHERE i."VAL_TOT" IS NOT NULL AND i."CNES" IS NOT NULL '
            'GROUP BY i."CNES" HAVING COUNT(*) > 1000 ORDER BY custo_por_dia ASC LIMIT 5'
        ),
        "tables": ["internacoes"],
        "adjustment_reason": "hospital esta vazia; agrupar por CNES da internacao.",
    },
    "GT122": {
        "question": "Quais procedimentos principais, ordenados por volume decrescente, cobrem até 80% das internações?",
        "query": (
            'SELECT proc_rea, nome_proc FROM ('
            'SELECT p."PROC_REA" AS proc_rea, p."NOME_PROC" AS nome_proc, COUNT(*) AS total_procedimentos, '
            'ROUND(SUM(COUNT(*)) OVER (ORDER BY COUNT(*) DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_acumulado '
            'FROM internacoes i JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'GROUP BY p."PROC_REA", p."NOME_PROC"'
            ') sub WHERE pct_acumulado <= 80 ORDER BY total_procedimentos DESC'
        ),
        "tables": ["internacoes", "procedimentos"],
        "adjustment_reason": "usar procedimento principal em internacoes.PROC_REA.",
    },
    "GT131": {
        "question": "Quais são os 5 procedimentos principais mais registrados em internações de pacientes indígenas?",
        "query": (
            'SELECT p."PROC_REA", p."NOME_PROC", COUNT(*) AS total_procedimentos '
            'FROM internacoes i JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'WHERE i."RACA_COR" = 5 '
            'GROUP BY p."PROC_REA", p."NOME_PROC" ORDER BY total_procedimentos DESC LIMIT 5'
        ),
        "tables": ["internacoes", "procedimentos"],
        "adjustment_reason": "usar procedimento principal em internacoes.PROC_REA.",
    },
    "GT132": {
        "question": "Quais os 3 CNES com maior valor médio de serviço hospitalar (VAL_SH) entre internações de residentes nos estados MA e RS?",
        "query": (
            'SELECT estado, "CNES", avg_val_sh FROM ('
            'SELECT mu."SG_UF" AS estado, i."CNES", ROUND(AVG(i."VAL_SH"), 2) AS avg_val_sh, '
            'ROW_NUMBER() OVER (PARTITION BY mu."SG_UF" ORDER BY AVG(i."VAL_SH") DESC) AS rn '
            'FROM internacoes i JOIN municipios mu ON i."MUNIC_RES" = mu."CO_MUNICIPIO_6D" '
            'WHERE mu."SG_UF" IN (\'MA\', \'RS\') AND i."VAL_SH" IS NOT NULL AND i."CNES" IS NOT NULL '
            'GROUP BY mu."SG_UF", i."CNES" HAVING COUNT(*) > 500'
            ') sub WHERE rn <= 3 ORDER BY estado, rn'
        ),
        "tables": ["internacoes", "municipios"],
        "adjustment_reason": "estado do hospital indisponivel; usar UF de residencia e CNES.",
    },
    "GT166": {
        "question": "Quantas internações estão sem código de procedimento principal realizado?",
        "query": 'SELECT COUNT(*) AS internacoes_sem_codigo_procedimento FROM internacoes WHERE "PROC_REA" IS NULL',
        "tables": ["internacoes"],
        "adjustment_reason": "internacao_procedimento nao existe; validar internacoes.PROC_REA.",
    },
    "GT185": {
        "question": "Quais são os 10 CNES com maior volume de internações em UTI?",
        "query": (
            'SELECT i."CNES", COALESCE(h."NO_HOSPITAL", \'Sem nome cadastrado\') AS hospital, COUNT(*) AS internacoes_uti '
            'FROM internacoes i LEFT JOIN hospital h ON i."CNES" = h."CNES" '
            'WHERE i."MARCA_UTI" <> 0 AND i."CNES" IS NOT NULL '
            'GROUP BY i."CNES", h."NO_HOSPITAL" ORDER BY internacoes_uti DESC LIMIT 10'
        ),
        "tables": ["internacoes", "hospital"],
        "adjustment_reason": "usar LEFT JOIN para nao perder internacoes porque hospital esta vazia.",
    },
    "GT186": {
        "question": "Quais são os 10 CNES com maior número absoluto de mortes?",
        "query": (
            'SELECT i."CNES", COALESCE(h."NO_HOSPITAL", \'Sem nome cadastrado\') AS hospital, COUNT(*) AS total_mortes '
            'FROM internacoes i LEFT JOIN hospital h ON i."CNES" = h."CNES" '
            'WHERE i."MORTE" = true AND i."CNES" IS NOT NULL '
            'GROUP BY i."CNES", h."NO_HOSPITAL" ORDER BY total_mortes DESC LIMIT 10'
        ),
        "tables": ["internacoes", "hospital"],
        "adjustment_reason": "usar LEFT JOIN para nao perder internacoes porque hospital esta vazia.",
    },
    "GT199": {
        "question": "Quais procedimentos principais foram mais registrados em internações com UTI?",
        "query": (
            'SELECT p."PROC_REA", p."NOME_PROC" AS procedimento, COUNT(*) AS total_procedimentos '
            'FROM internacoes i JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'WHERE i."MARCA_UTI" <> 0 GROUP BY p."PROC_REA", p."NOME_PROC" '
            'ORDER BY total_procedimentos DESC LIMIT 10'
        ),
        "tables": ["internacoes", "procedimentos"],
        "adjustment_reason": "usar procedimento principal em internacoes.PROC_REA.",
    },
    "GT209": {
        "question": "Qual CNES tem maior taxa de mortalidade por especialidade, considerando apenas combinações com mais de 1000 internações?",
        "query": (
            'WITH agg AS (SELECT e."DESCRICAO" AS especialidade, i."CNES", '
            'COALESCE(h."NO_HOSPITAL", \'Sem nome cadastrado\') AS hospital, '
            'COUNT(*) AS total_internacoes, SUM(CASE WHEN i."MORTE" = true THEN 1 ELSE 0 END) AS total_mortes, '
            'ROUND(SUM(CASE WHEN i."MORTE" = true THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) AS taxa_mortalidade '
            'FROM internacoes i JOIN especialidade e ON i."ESPEC" = e."ESPEC" '
            'LEFT JOIN hospital h ON i."CNES" = h."CNES" '
            'WHERE i."CNES" IS NOT NULL '
            'GROUP BY e."DESCRICAO", i."CNES", h."NO_HOSPITAL" HAVING COUNT(*) > 1000) '
            'SELECT * FROM agg ORDER BY taxa_mortalidade DESC LIMIT 1'
        ),
        "tables": ["internacoes", "especialidade", "hospital"],
        "adjustment_reason": "usar LEFT JOIN para nao perder internacoes porque hospital esta vazia.",
    },
    "GT210": {
        "question": "Qual procedimento principal mais frequente em cada capítulo CID?",
        "query": (
            'WITH agg AS (SELECT c."DS_CAPITULO" AS capitulo_cid, p."PROC_REA", p."NOME_PROC" AS procedimento, COUNT(*) AS total_procedimentos '
            'FROM internacoes i JOIN cid c ON i."DIAG_PRINC" = c."CID" '
            'JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'GROUP BY c."DS_CAPITULO", p."PROC_REA", p."NOME_PROC"), '
            'ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY capitulo_cid ORDER BY total_procedimentos DESC) AS rn FROM agg) '
            'SELECT capitulo_cid, "PROC_REA", procedimento, total_procedimentos FROM ranked WHERE rn = 1 '
            'ORDER BY total_procedimentos DESC LIMIT 20'
        ),
        "tables": ["internacoes", "cid", "procedimentos"],
        "adjustment_reason": "usar procedimento principal em internacoes.PROC_REA.",
    },
    "GT214": {
        "question": "Quais CNES com mais de 5000 internações têm custo médio e taxa de mortalidade acima da média geral?",
        "query": (
            'WITH por_hospital AS (SELECT i."CNES", COALESCE(h."NO_HOSPITAL", \'Sem nome cadastrado\') AS hospital, '
            'COUNT(*) AS total_internacoes, AVG(i."VAL_TOT") AS custo_medio, '
            'SUM(CASE WHEN i."MORTE" = true THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0) AS taxa_mortalidade '
            'FROM internacoes i LEFT JOIN hospital h ON i."CNES" = h."CNES" '
            'WHERE i."VAL_TOT" IS NOT NULL AND i."CNES" IS NOT NULL '
            'GROUP BY i."CNES", h."NO_HOSPITAL" HAVING COUNT(*) > 5000), '
            'medias AS (SELECT AVG("VAL_TOT") AS custo_medio_geral, '
            'SUM(CASE WHEN "MORTE" = true THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0) AS taxa_mortalidade_geral '
            'FROM internacoes WHERE "VAL_TOT" IS NOT NULL) '
            'SELECT p.* FROM por_hospital p, medias m '
            'WHERE p.custo_medio > m.custo_medio_geral AND p.taxa_mortalidade > m.taxa_mortalidade_geral '
            'ORDER BY p.taxa_mortalidade DESC, p.custo_medio DESC'
        ),
        "tables": ["internacoes", "hospital"],
        "adjustment_reason": "usar LEFT JOIN para nao perder internacoes porque hospital esta vazia.",
    },
    "GT221": {
        "question": "Quais são os 5 CNES por UF de residência MA e RS com maior taxa de mortalidade em internações com UTI, considerando mais de 500 internações em UTI?",
        "query": (
            'WITH agg AS (SELECT m."SG_UF" AS uf_residencia, i."CNES", COUNT(*) AS total_uti, '
            'SUM(CASE WHEN i."MORTE" = true THEN 1 ELSE 0 END) AS mortes_uti, '
            'ROUND(SUM(CASE WHEN i."MORTE" = true THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) AS taxa_mortalidade_uti '
            'FROM internacoes i JOIN municipios m ON i."MUNIC_RES" = m."CO_MUNICIPIO_6D" '
            'WHERE m."SG_UF" IN (\'MA\', \'RS\') AND i."MARCA_UTI" <> 0 AND i."CNES" IS NOT NULL '
            'GROUP BY m."SG_UF", i."CNES" HAVING COUNT(*) > 500), '
            'ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY uf_residencia ORDER BY taxa_mortalidade_uti DESC, total_uti DESC) AS rn FROM agg) '
            'SELECT uf_residencia, "CNES", total_uti, mortes_uti, taxa_mortalidade_uti '
            'FROM ranked WHERE rn <= 5 ORDER BY uf_residencia, rn'
        ),
        "tables": ["internacoes", "municipios"],
        "adjustment_reason": "estado do hospital indisponivel; usar UF de residencia e CNES.",
    },
    "GT226": {
        "question": "Quais procedimentos principais cobrem 80% dos procedimentos principais em internações com UTI?",
        "query": (
            'WITH proc_counts AS (SELECT p."PROC_REA", p."NOME_PROC" AS procedimento, COUNT(*) AS total_procedimentos '
            'FROM internacoes i JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'WHERE i."MARCA_UTI" <> 0 GROUP BY p."PROC_REA", p."NOME_PROC"), '
            'ranked AS (SELECT "PROC_REA", procedimento, total_procedimentos, '
            'SUM(total_procedimentos) OVER (ORDER BY total_procedimentos DESC, procedimento) AS acumulado, '
            'SUM(total_procedimentos) OVER () AS total_geral FROM proc_counts) '
            'SELECT "PROC_REA", procedimento, total_procedimentos, ROUND(acumulado * 100.0 / NULLIF(total_geral, 0), 2) AS percentual_acumulado '
            'FROM ranked WHERE acumulado <= total_geral * 0.8 OR acumulado - total_procedimentos < total_geral * 0.8 '
            'ORDER BY total_procedimentos DESC'
        ),
        "tables": ["internacoes", "procedimentos"],
        "adjustment_reason": "usar procedimento principal em internacoes.PROC_REA.",
    },
    "GT227": {
        "question": "Quais são os 3 procedimentos principais mais registrados por sexo e faixa etária?",
        "query": (
            'WITH base AS (SELECT s."DESCRICAO" AS sexo, '
            'CASE WHEN i."IDADE" < 18 THEN \'<18\' WHEN i."IDADE" BETWEEN 18 AND 64 THEN \'18-64\' ELSE \'65+\' END AS faixa_etaria, '
            'p."PROC_REA", p."NOME_PROC" AS procedimento, COUNT(*) AS total_procedimentos '
            'FROM internacoes i JOIN sexo s ON i."SEXO" = s."SEXO" '
            'JOIN procedimentos p ON i."PROC_REA" = p."PROC_REA" '
            'WHERE i."IDADE" IS NOT NULL GROUP BY s."DESCRICAO", faixa_etaria, p."PROC_REA", p."NOME_PROC"), '
            'ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY sexo, faixa_etaria ORDER BY total_procedimentos DESC) AS rn FROM base) '
            'SELECT sexo, faixa_etaria, "PROC_REA", procedimento, total_procedimentos '
            'FROM ranked WHERE rn <= 3 ORDER BY sexo, faixa_etaria, rn'
        ),
        "tables": ["internacoes", "sexo", "procedimentos"],
        "adjustment_reason": "usar procedimento principal em internacoes.PROC_REA.",
    },
}


QUESTION_PREFIX_OVERRIDES: dict[str, str] = {
    "GT018": "Quando houver dados socioeconômicos, quantos habitantes tem o município com a maior população registrada?",
    "GT040": "Quando houver dados socioeconômicos, qual a taxa de mortalidade infantil média registrada?",
    "GT189": "Quando houver dados socioeconômicos, qual a média de médicos por mil habitantes por UF em 2021?",
    "GT190": "Quando houver dados socioeconômicos, quais municípios tiveram maior taxa de mortalidade infantil em 2021?",
    "GT222": "Quando houver dados socioeconômicos, quais municípios tiveram maior taxa de internação por mil habitantes em 2021?",
    "GT223": "Quando houver dados socioeconômicos, como a taxa de internação por mil habitantes em 2021 varia por quintil de PIB per capita?",
    "GT224": "Quando houver dados socioeconômicos, como a taxa de mortalidade hospitalar em 2021 varia por quintil de leitos SUS por mil habitantes?",
    "GT228": "Quando houver cadastro de município do hospital, quantas internações ocorreram com estado de residência diferente do estado do hospital por ano?",
    "GT229": "Quando houver cadastro de município do hospital, quais pares de estado de residência e estado do hospital tiveram maior volume de internações interestaduais?",
}


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def result_hash(columns: list[str], rows: list[dict[str, Any]]) -> str:
    payload = {"columns": columns, "rows": rows}
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=json_default)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def summarize_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Sem linhas retornadas."
    if len(rows) == 1:
        return "Resultado unico: " + ", ".join(f"{k}={v}" for k, v in rows[0].items()) + "."
    return f"Resultado com {len(rows)} linhas; primeira linha: {rows[0]}."


def apply_overrides(item: dict[str, Any]) -> dict[str, Any]:
    updated = dict(item)
    adjustment_reasons = []
    override = OVERRIDES.get(item["id"])
    if override:
        for key in ("question", "query", "tables"):
            if key in override:
                updated[key] = override[key]
        adjustment_reasons.append(override["adjustment_reason"])
    if item["id"] in QUESTION_PREFIX_OVERRIDES:
        updated["question"] = QUESTION_PREFIX_OVERRIDES[item["id"]]
        adjustment_reasons.append("Pergunta ajustada para explicitar limitacao/cobertura do banco atual.")
    if adjustment_reasons:
        updated["schema_migration_status"] = "validated_adjusted_current_duckdb"
        updated["schema_migration_note"] = " ".join(adjustment_reasons)
    else:
        updated["schema_migration_status"] = "validated_current_duckdb"
        updated["schema_migration_note"] = "SQL executada com sucesso no DuckDB atual."
    return updated


def execute_item(
    con: duckdb.DuckDBPyConnection,
    *,
    item: dict[str, Any],
    evidence_dir: Path,
    db_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sql = item["query"].strip().rstrip(";")
    start = time.perf_counter()
    cursor = con.execute(sql)
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    raw_rows = cursor.fetchall()
    duration = time.perf_counter() - start
    rows = [
        {columns[idx]: normalize_value(value) for idx, value in enumerate(row)}
        for row in raw_rows
    ]
    evidence = {
        "id": item["id"],
        "question_pt": item["question"],
        "executed_at": datetime.now(UTC).isoformat(),
        "database_file": str(db_path),
        "sql": sql,
        "duration_seconds": round(duration, 6),
        "performance_class": "fast" if duration < 1 else "medium" if duration < 10 else "slow",
        "row_count": len(rows),
        "columns": columns,
        "preview_rows": rows[:50],
        "result_hash": result_hash(columns, rows),
        "semantic_disposition": "accepted",
    }
    evidence_path = evidence_dir / f"{item['id']}.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=True, default=json_default),
        encoding="utf-8",
    )
    return evidence, {
        "row_count": len(rows),
        "result_summary": summarize_rows(rows),
        "duration_seconds": round(duration, 6),
        "validation_evidence": str(evidence_path),
    }


def infer_result_type(item: dict[str, Any], evidence: dict[str, Any]) -> str:
    question = item["question"].lower()
    if evidence["row_count"] == 1:
        return "scalar"
    if any(term in question for term in ("evolução", "evolucao", "anual", "ano", "mês", "mes")):
        return "time_series"
    if any(term in question for term in ("quais", "top", "maior", "maiores", "mais comuns", "mais registrados")):
        return "ranking"
    return "distribution"


def to_ground_truth_payload(item: dict[str, Any], evidence: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    notes = item.get("notes", "")
    migration_note = item.get("schema_migration_note", "")
    if item.get("schema_migration_status") == "validated_adjusted_current_duckdb":
        data_quality_notes = migration_note
    elif notes and migration_note:
        data_quality_notes = f"{notes} | {migration_note}"
    else:
        data_quality_notes = notes or migration_note
    return {
        "id": item["id"],
        "persona": "Analista DATASUS/SIH",
        "question_pt": item["question"],
        "difficulty": item.get("difficulty"),
        "sql": item["query"].strip().rstrip(";"),
        "tables_used": item.get("tables", []),
        "columns_used": evidence["columns"],
        "expected_result_type": infer_result_type(item, evidence),
        "execution_status": "passed",
        "row_count": execution["row_count"],
        "result_summary": execution["result_summary"],
        "validation_evidence": execution["validation_evidence"],
        "assumptions": "Validado contra o DuckDB atual do projeto.",
        "data_quality_notes": data_quality_notes,
        "duration_seconds": execution["duration_seconds"],
        "created_at": datetime.now(UTC).date().isoformat(),
        "semantic_disposition": "accepted",
    }


def write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=True, default=json_default))
            handle.write("\n")


def main() -> int:
    cfg = load_config()
    source_path = cfg.project_root / ROOT_INPUT
    items = json.loads(source_path.read_text(encoding="utf-8"))
    output_json = cfg.project_root / OUTPUT_JSON
    output_jsonl = cfg.project_root / OUTPUT_JSONL
    report_json = cfg.project_root / REPORT_JSON
    report_md = cfg.project_root / REPORT_MD
    evidence_dir = cfg.project_root / EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)

    corrected_items = [apply_overrides(item) for item in items]
    payloads: list[dict[str, Any]] = []
    evidence_payloads: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    started = time.perf_counter()

    con = duckdb.connect(str(cfg.db_path), read_only=True)
    try:
        for item in corrected_items:
            try:
                evidence, execution = execute_item(
                    con,
                    item=item,
                    evidence_dir=evidence_dir,
                    db_path=cfg.db_path,
                )
                evidence_payloads.append(evidence)
                payloads.append(to_ground_truth_payload(item, evidence, execution))
            except Exception as exc:
                errors.append(
                    {
                        "id": item["id"],
                        "question": item["question"],
                        "sql": item["query"],
                        "error": str(exc),
                    }
                )
    finally:
        con.close()

    adjusted_ids = sorted(
        item["id"]
        for item in corrected_items
        if item.get("schema_migration_status") == "validated_adjusted_current_duckdb"
    )
    adjusted_details = [
        {
            "id": item["id"],
            "question": item["question"],
            "tables": item.get("tables", []),
            "reason": item.get("schema_migration_note", ""),
        }
        for item in corrected_items
        if item.get("schema_migration_status") == "validated_adjusted_current_duckdb"
    ]
    table_counts: dict[str, int] = {}
    for payload in payloads:
        for table in payload["tables_used"]:
            table_counts[table] = table_counts.get(table, 0) + 1

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "source": str(source_path),
        "db_path": str(cfg.db_path),
        "total_source_items": len(items),
        "validated_items": len(payloads),
        "failed_items": len(errors),
        "adjusted_items": len(adjusted_ids),
        "adjusted_ids": adjusted_ids,
        "adjusted_details": adjusted_details,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "outputs": {
            "json": str(output_json),
            "jsonl": str(output_jsonl),
            "evidence_dir": str(evidence_dir),
            "report_json": str(report_json),
            "report_md": str(report_md),
        },
        "table_counts": dict(sorted(table_counts.items())),
        "errors": errors,
    }

    if errors:
        report_json.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        raise SystemExit(f"Validation failed for {len(errors)} item(s); see {report_json}")

    output_json.write_text(
        json.dumps(payloads, indent=2, ensure_ascii=True, default=json_default),
        encoding="utf-8",
    )
    write_jsonl(output_jsonl, payloads)
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    md = [
        "# Ground truth 228 validation",
        "",
        f"Source: `{source_path}`",
        f"Database: `{cfg.db_path}`",
        f"Created at: `{report['created_at']}`",
        "",
        "## Summary",
        "",
        f"- Source items: {len(items)}",
        f"- Validated items: {len(payloads)}",
        f"- Failed items: {len(errors)}",
        f"- Adjusted items: {len(adjusted_ids)}",
        f"- Elapsed seconds: {report['elapsed_seconds']}",
        "",
        "## Outputs",
        "",
        f"- JSON: `{output_json}`",
        f"- JSONL: `{output_jsonl}`",
        f"- Evidence dir: `{evidence_dir}`",
        "",
        "## Adjusted IDs",
        "",
        ", ".join(adjusted_ids) if adjusted_ids else "None",
        "",
        "## Adjusted Details",
        "",
        "| ID | Final question | Tables | Reason |",
        "| --- | --- | --- | --- |",
        *[
            "| {id} | {question} | {tables} | {reason} |".format(
                id=detail["id"],
                question=str(detail["question"]).replace("|", "\\|"),
                tables=", ".join(detail["tables"]).replace("|", "\\|"),
                reason=str(detail["reason"]).replace("|", "\\|"),
            )
            for detail in adjusted_details
        ],
        "",
        "## Notes",
        "",
        "- All final SQL statements were executed against the current DuckDB database.",
        "- Items that previously depended on `internacao_procedimento` were rewritten to use the principal procedure in `internacoes.PROC_REA`.",
        "- Items that depended on the empty `hospital` dimension were either rewritten to use `internacoes.CNES` or explicitly scoped to available current data.",
        "- Socioeconomic questions were explicitly scoped to the fact that results depend on available rows in `socioeconomico`, which is empty in the current database.",
    ]
    report_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
