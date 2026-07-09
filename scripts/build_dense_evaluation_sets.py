from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from health_system_chatbot.config import load_config


@dataclass(frozen=True)
class DenseQuestion:
    id: str
    question_pt: str
    sql: str
    difficulty: str
    tables_used: list[str]
    columns_used: list[str]
    expected_result_type: str
    assumptions: str = ""
    data_quality_notes: str = ""


TABLE_QUESTIONS: list[DenseQuestion] = [
    DenseQuestion(
        id="DENSE_TABLE_001",
        question_pt="Quantos registros existem na tabela de staging de internacoes?",
        sql="SELECT COUNT(*) AS total_registros_staging FROM _staging_internacoes",
        difficulty="L1",
        tables_used=["_staging_internacoes"],
        columns_used=[],
        expected_result_type="scalar",
        data_quality_notes="Tabela de staging; pode ter contagem diferente da tabela analitica internacoes.",
    ),
    DenseQuestion(
        id="DENSE_TABLE_002",
        question_pt="Quais codigos e descricoes existem para carater de internacao?",
        sql="SELECT CAR_INT, DESCRICAO FROM car_int ORDER BY CAR_INT",
        difficulty="L1",
        tables_used=["car_int"],
        columns_used=["car_int.CAR_INT", "car_int.DESCRICAO"],
        expected_result_type="ordered",
    ),
    DenseQuestion(
        id="DENSE_TABLE_003",
        question_pt="Quantos codigos ocupacionais existem na dimensao CBOR?",
        sql="SELECT COUNT(*) AS total_cbor FROM cbor",
        difficulty="L1",
        tables_used=["cbor"],
        columns_used=[],
        expected_result_type="scalar",
    ),
    DenseQuestion(
        id="DENSE_TABLE_004",
        question_pt="Quantos CIDs existem por capitulo no catalogo CID?",
        sql=(
            "SELECT DS_CAPITULO, COUNT(*) AS total_cids "
            "FROM cid GROUP BY 1 ORDER BY total_cids DESC, DS_CAPITULO"
        ),
        difficulty="L1",
        tables_used=["cid"],
        columns_used=["cid.DS_CAPITULO"],
        expected_result_type="distribution",
    ),
    DenseQuestion(
        id="DENSE_TABLE_005",
        question_pt="Quais codigos e descricoes existem para complexidade?",
        sql="SELECT COMPLEX, DESCRICAO FROM complexidade ORDER BY COMPLEX",
        difficulty="L1",
        tables_used=["complexidade"],
        columns_used=["complexidade.COMPLEX", "complexidade.DESCRICAO"],
        expected_result_type="ordered",
    ),
    DenseQuestion(
        id="DENSE_TABLE_006",
        question_pt="Quantos tipos de contraceptivos existem no catalogo?",
        sql="SELECT COUNT(*) AS total_contraceptivos FROM contraceptivos",
        difficulty="L1",
        tables_used=["contraceptivos"],
        columns_used=[],
        expected_result_type="scalar",
    ),
    DenseQuestion(
        id="DENSE_TABLE_007",
        question_pt="Quais especialidades existem no catalogo de especialidade?",
        sql="SELECT ESPEC, DESCRICAO FROM especialidade ORDER BY ESPEC",
        difficulty="L1",
        tables_used=["especialidade"],
        columns_used=["especialidade.ESPEC", "especialidade.DESCRICAO"],
        expected_result_type="ordered",
    ),
    DenseQuestion(
        id="DENSE_TABLE_008",
        question_pt="Quantos registros existem na dimensao de etnia?",
        sql="SELECT COUNT(*) AS total_etnias FROM etnia",
        difficulty="L1",
        tables_used=["etnia"],
        columns_used=[],
        expected_result_type="scalar",
    ),
    DenseQuestion(
        id="DENSE_TABLE_009",
        question_pt="Quantos hospitais existem no cadastro hospitalar carregado?",
        sql="SELECT COUNT(*) AS total_hospitais FROM hospital",
        difficulty="L1",
        tables_used=["hospital"],
        columns_used=[],
        expected_result_type="scalar",
        data_quality_notes="No banco atual a tabela hospital esta vazia.",
    ),
    DenseQuestion(
        id="DENSE_TABLE_010",
        question_pt="Quais codigos e descricoes existem para instrucao?",
        sql="SELECT INSTRU, DESCRICAO FROM instrucao ORDER BY INSTRU",
        difficulty="L1",
        tables_used=["instrucao"],
        columns_used=["instrucao.INSTRU", "instrucao.DESCRICAO"],
        expected_result_type="ordered",
    ),
    DenseQuestion(
        id="DENSE_TABLE_011",
        question_pt="Qual e o volume, mortes e valor total na tabela de internacoes?",
        sql=(
            "SELECT COUNT(*) AS internacoes, "
            "COUNT(*) FILTER (WHERE MORTE) AS mortes, "
            "ROUND(SUM(CAST(VAL_TOT AS DECIMAL(20,2))), 2) AS valor_total "
            "FROM internacoes"
        ),
        difficulty="L1",
        tables_used=["internacoes"],
        columns_used=["internacoes.MORTE", "internacoes.VAL_TOT"],
        expected_result_type="scalar",
    ),
    DenseQuestion(
        id="DENSE_TABLE_012",
        question_pt="Quais codigos e descricoes existem para marca de UTI?",
        sql="SELECT MARCA_UTI, DESCRICAO FROM marca_uti ORDER BY MARCA_UTI",
        difficulty="L1",
        tables_used=["marca_uti"],
        columns_used=["marca_uti.MARCA_UTI", "marca_uti.DESCRICAO"],
        expected_result_type="ordered",
    ),
    DenseQuestion(
        id="DENSE_TABLE_013",
        question_pt="Quantos municipios existem e quantas UFs validas aparecem na dimensao territorial?",
        sql=(
            "WITH valid_uf(sg_uf) AS (VALUES ('AC'), ('AL'), ('AP'), ('AM'), ('BA'), "
            "('CE'), ('DF'), ('ES'), ('GO'), ('MA'), ('MT'), ('MS'), ('MG'), ('PA'), "
            "('PB'), ('PR'), ('PE'), ('PI'), ('RJ'), ('RN'), ('RS'), ('RO'), ('RR'), "
            "('SC'), ('SP'), ('SE'), ('TO')) "
            "SELECT COUNT(*) AS total_municipios, "
            "COUNT(DISTINCT m.SG_UF) FILTER (WHERE v.sg_uf IS NOT NULL) AS ufs_validas, "
            "COUNT(DISTINCT m.SG_UF) FILTER (WHERE v.sg_uf IS NULL) AS codigos_sg_uf_invalidos "
            "FROM municipios m LEFT JOIN valid_uf v ON m.SG_UF = v.sg_uf"
        ),
        difficulty="L1",
        tables_used=["municipios"],
        columns_used=["municipios.SG_UF"],
        expected_result_type="scalar",
    ),
    DenseQuestion(
        id="DENSE_TABLE_014",
        question_pt="Quantos registros existem na dimensao de nacionalidade?",
        sql="SELECT COUNT(*) AS total_nacionalidades FROM nacionalidade",
        difficulty="L1",
        tables_used=["nacionalidade"],
        columns_used=[],
        expected_result_type="scalar",
    ),
    DenseQuestion(
        id="DENSE_TABLE_015",
        question_pt="Quantos procedimentos existem no catalogo de procedimentos?",
        sql="SELECT COUNT(*) AS total_procedimentos FROM procedimentos",
        difficulty="L1",
        tables_used=["procedimentos"],
        columns_used=[],
        expected_result_type="scalar",
    ),
    DenseQuestion(
        id="DENSE_TABLE_016",
        question_pt="Quais codigos e descricoes existem para raca cor?",
        sql="SELECT RACA_COR, DESCRICAO FROM raca_cor ORDER BY RACA_COR",
        difficulty="L1",
        tables_used=["raca_cor"],
        columns_used=["raca_cor.RACA_COR", "raca_cor.DESCRICAO"],
        expected_result_type="ordered",
        data_quality_notes="Relacionamento com internacoes e rejeitado para respostas de negocio.",
    ),
    DenseQuestion(
        id="DENSE_TABLE_017",
        question_pt="Quais codigos e descricoes existem para sexo?",
        sql="SELECT SEXO, DESCRICAO FROM sexo ORDER BY SEXO",
        difficulty="L1",
        tables_used=["sexo"],
        columns_used=["sexo.SEXO", "sexo.DESCRICAO"],
        expected_result_type="ordered",
    ),
    DenseQuestion(
        id="DENSE_TABLE_018",
        question_pt="Qual e o intervalo de anos e total de registros socioeconomicos carregados?",
        sql="SELECT MIN(NU_ANO) AS primeiro_ano, MAX(NU_ANO) AS ultimo_ano, COUNT(*) AS registros FROM socioeconomico",
        difficulty="L1",
        tables_used=["socioeconomico"],
        columns_used=["socioeconomico.NU_ANO"],
        expected_result_type="scalar",
        data_quality_notes="No banco atual a tabela socioeconomico esta vazia.",
    ),
    DenseQuestion(
        id="DENSE_TABLE_019",
        question_pt="Qual e o intervalo de datas disponivel na dimensao tempo?",
        sql="SELECT MIN(data) AS primeira_data, MAX(data) AS ultima_data, COUNT(*) AS dias FROM tempo",
        difficulty="L1",
        tables_used=["tempo"],
        columns_used=["tempo.data"],
        expected_result_type="scalar",
    ),
    DenseQuestion(
        id="DENSE_TABLE_020",
        question_pt="Quais codigos e descricoes existem para vinculo previdenciario?",
        sql="SELECT VINCPREV, DESCRICAO FROM vincprev ORDER BY VINCPREV",
        difficulty="L1",
        tables_used=["vincprev"],
        columns_used=["vincprev.VINCPREV", "vincprev.DESCRICAO"],
        expected_result_type="ordered",
        data_quality_notes="Relacionamento com internacoes e rejeitado para respostas de negocio.",
    ),
]


JOIN_QUESTIONS: list[DenseQuestion] = [
    DenseQuestion(
        id="DENSE_JOIN_001",
        question_pt="Como as internacoes se distribuem por sexo?",
        sql=(
            "SELECT s.DESCRICAO AS sexo, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN sexo s ON i.SEXO = s.SEXO "
            "GROUP BY 1 ORDER BY internacoes DESC"
        ),
        difficulty="L2",
        tables_used=["internacoes", "sexo"],
        columns_used=["internacoes.SEXO", "sexo.SEXO"],
        expected_result_type="distribution",
    ),
    DenseQuestion(
        id="DENSE_JOIN_002",
        question_pt="Como as internacoes se distribuem por carater de internacao?",
        sql=(
            "SELECT c.DESCRICAO AS carater, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN car_int c ON i.CAR_INT = c.CAR_INT "
            "GROUP BY 1 ORDER BY internacoes DESC"
        ),
        difficulty="L2",
        tables_used=["internacoes", "car_int"],
        columns_used=["internacoes.CAR_INT", "car_int.CAR_INT"],
        expected_result_type="distribution",
    ),
    DenseQuestion(
        id="DENSE_JOIN_003",
        question_pt="Qual e o total de internacoes e valor total por codigo de complexidade validado na dimensao?",
        sql=(
            "SELECT i.COMPLEX, COUNT(*) AS internacoes, "
            "ROUND(SUM(CAST(i.VAL_TOT AS DECIMAL(20,2))), 2) AS valor_total "
            "FROM internacoes i JOIN complexidade c ON i.COMPLEX = c.COMPLEX "
            "GROUP BY 1 ORDER BY internacoes DESC"
        ),
        difficulty="L2",
        tables_used=["internacoes", "complexidade"],
        columns_used=["internacoes.COMPLEX", "complexidade.COMPLEX", "internacoes.VAL_TOT"],
        expected_result_type="distribution",
    ),
    DenseQuestion(
        id="DENSE_JOIN_004",
        question_pt="Quais descricoes de complexidade tem mais internacoes e qual o valor total?",
        sql=(
            "SELECT c.DESCRICAO AS complexidade, COUNT(*) AS internacoes, "
            "ROUND(SUM(CAST(i.VAL_TOT AS DECIMAL(20,2))), 2) AS valor_total "
            "FROM internacoes i JOIN complexidade c ON i.COMPLEX = c.COMPLEX "
            "GROUP BY 1 ORDER BY internacoes DESC"
        ),
        difficulty="L2",
        tables_used=["internacoes", "complexidade"],
        columns_used=["internacoes.COMPLEX", "complexidade.COMPLEX", "internacoes.VAL_TOT"],
        expected_result_type="distribution",
    ),
    DenseQuestion(
        id="DENSE_JOIN_005",
        question_pt="Quais especialidades tiveram mais internacoes?",
        sql=(
            "SELECT e.DESCRICAO AS especialidade, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN especialidade e ON i.ESPEC = e.ESPEC "
            "GROUP BY 1 ORDER BY internacoes DESC LIMIT 20"
        ),
        difficulty="L2",
        tables_used=["internacoes", "especialidade"],
        columns_used=["internacoes.ESPEC", "especialidade.ESPEC"],
        expected_result_type="ranking",
    ),
    DenseQuestion(
        id="DENSE_JOIN_006",
        question_pt="Como as internacoes se distribuem por marca de UTI?",
        sql=(
            "SELECT m.DESCRICAO AS marca_uti, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN marca_uti m ON i.MARCA_UTI = m.MARCA_UTI "
            "GROUP BY 1 ORDER BY internacoes DESC"
        ),
        difficulty="L2",
        tables_used=["internacoes", "marca_uti"],
        columns_used=["internacoes.MARCA_UTI", "marca_uti.MARCA_UTI"],
        expected_result_type="distribution",
    ),
    DenseQuestion(
        id="DENSE_JOIN_007",
        question_pt="Quais nacionalidades tiveram mais internacoes?",
        sql=(
            "SELECT n.DESCRICAO AS nacionalidade, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN nacionalidade n ON i.NACIONAL = n.NACIONAL "
            "GROUP BY 1 ORDER BY internacoes DESC LIMIT 20"
        ),
        difficulty="L2",
        tables_used=["internacoes", "nacionalidade"],
        columns_used=["internacoes.NACIONAL", "nacionalidade.NACIONAL"],
        expected_result_type="ranking",
    ),
    DenseQuestion(
        id="DENSE_JOIN_008",
        question_pt="Quais diagnosticos principais foram mais frequentes com descricao CID?",
        sql=(
            "SELECT c.CID, c.DESCRICAO, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN cid c ON i.DIAG_PRINC = c.CID "
            "GROUP BY 1, 2 ORDER BY internacoes DESC LIMIT 20"
        ),
        difficulty="L2",
        tables_used=["internacoes", "cid"],
        columns_used=["internacoes.DIAG_PRINC", "cid.CID", "cid.DESCRICAO"],
        expected_result_type="ranking",
    ),
    DenseQuestion(
        id="DENSE_JOIN_009",
        question_pt="Qual e o total de internacoes por UF de residencia mapeada?",
        sql=(
            "SELECT m.SG_UF, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN municipios m ON i.MUNIC_RES = m.CO_MUNICIPIO_6D "
            "GROUP BY 1 ORDER BY internacoes DESC"
        ),
        difficulty="L3",
        tables_used=["internacoes", "municipios"],
        columns_used=["internacoes.MUNIC_RES", "municipios.CO_MUNICIPIO_6D", "municipios.SG_UF"],
        expected_result_type="distribution",
        assumptions="Restrito a internacoes com municipio de residencia mapeado.",
    ),
    DenseQuestion(
        id="DENSE_JOIN_010",
        question_pt="Quais regioes de saude tiveram mais internacoes por residencia mapeada?",
        sql=(
            "SELECT m.SG_UF, m.NO_REGIAO_SAUDE, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN municipios m ON i.MUNIC_RES = m.CO_MUNICIPIO_6D "
            "GROUP BY 1, 2 ORDER BY internacoes DESC LIMIT 20"
        ),
        difficulty="L3",
        tables_used=["internacoes", "municipios"],
        columns_used=["internacoes.MUNIC_RES", "municipios.NO_REGIAO_SAUDE", "municipios.SG_UF"],
        expected_result_type="ranking",
        assumptions="Restrito a internacoes com municipio de residencia mapeado.",
    ),
    DenseQuestion(
        id="DENSE_JOIN_011",
        question_pt="Quais procedimentos principais das internacoes aparecem mais no catalogo de procedimentos?",
        sql=(
            "SELECT p.PROC_REA, p.NOME_PROC, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN procedimentos p ON i.PROC_REA = p.PROC_REA "
            "GROUP BY 1, 2 ORDER BY internacoes DESC LIMIT 20"
        ),
        difficulty="L2",
        tables_used=["internacoes", "procedimentos"],
        columns_used=["internacoes.PROC_REA", "procedimentos.PROC_REA", "procedimentos.NOME_PROC"],
        expected_result_type="ranking",
    ),
    DenseQuestion(
        id="DENSE_JOIN_012",
        question_pt="Quantas internacoes ocorreram por ano usando a dimensao tempo?",
        sql=(
            "SELECT t.ano, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN tempo t ON i.DT_INTER = t.data "
            "GROUP BY 1 ORDER BY 1"
        ),
        difficulty="L2",
        tables_used=["internacoes", "tempo"],
        columns_used=["internacoes.DT_INTER", "tempo.data", "tempo.ano"],
        expected_result_type="time_series",
    ),
    DenseQuestion(
        id="DENSE_JOIN_013",
        question_pt="Como as internacoes com contraceptivo 1 informado se distribuem por tipo de contraceptivo?",
        sql=(
            "SELECT c.DESCRICAO AS contraceptivo, COUNT(*) AS internacoes "
            "FROM internacoes i JOIN contraceptivos c ON i.CONTRACEP1 = c.CONTRACEPTIVO "
            "GROUP BY 1 ORDER BY internacoes DESC"
        ),
        difficulty="L2",
        tables_used=["internacoes", "contraceptivos"],
        columns_used=["internacoes.CONTRACEP1", "contraceptivos.CONTRACEPTIVO"],
        expected_result_type="distribution",
    ),
    DenseQuestion(
        id="DENSE_JOIN_014",
        question_pt="Auditoria: quantas internacoes tem codigo de raca cor sem correspondencia na dimensao?",
        sql=(
            "SELECT COUNT(*) FILTER (WHERE r.RACA_COR IS NULL) AS sem_correspondencia, "
            "COUNT(*) AS internacoes "
            "FROM internacoes i LEFT JOIN raca_cor r ON i.RACA_COR = r.RACA_COR"
        ),
        difficulty="L3",
        tables_used=["internacoes", "raca_cor"],
        columns_used=["internacoes.RACA_COR", "raca_cor.RACA_COR"],
        expected_result_type="data_quality_finding",
    ),
    DenseQuestion(
        id="DENSE_JOIN_015",
        question_pt="Auditoria: quantas internacoes tem instrucao sem correspondencia na dimensao?",
        sql=(
            "SELECT COUNT(*) FILTER (WHERE ins.INSTRU IS NULL) AS sem_correspondencia, "
            "COUNT(*) AS internacoes "
            "FROM internacoes i LEFT JOIN instrucao ins ON i.INSTRU = ins.INSTRU"
        ),
        difficulty="L3",
        tables_used=["internacoes", "instrucao"],
        columns_used=["internacoes.INSTRU", "instrucao.INSTRU"],
        expected_result_type="data_quality_finding",
    ),
    DenseQuestion(
        id="DENSE_JOIN_016",
        question_pt="Auditoria: quantas internacoes tem vinculo previdenciario sem correspondencia na dimensao?",
        sql=(
            "SELECT COUNT(*) FILTER (WHERE v.VINCPREV IS NULL) AS sem_correspondencia, "
            "COUNT(*) AS internacoes "
            "FROM internacoes i LEFT JOIN vincprev v ON i.VINCPREV = v.VINCPREV"
        ),
        difficulty="L3",
        tables_used=["internacoes", "vincprev"],
        columns_used=["internacoes.VINCPREV", "vincprev.VINCPREV"],
        expected_result_type="data_quality_finding",
    ),
    DenseQuestion(
        id="DENSE_JOIN_017",
        question_pt="Auditoria: quantas internacoes tem CBOR sem correspondencia na dimensao ocupacional?",
        sql=(
            "SELECT COUNT(*) FILTER (WHERE c.CBOR IS NULL) AS sem_correspondencia, "
            "COUNT(*) AS internacoes "
            "FROM internacoes i LEFT JOIN cbor c ON i.CBOR = c.CBOR"
        ),
        difficulty="L3",
        tables_used=["internacoes", "cbor"],
        columns_used=["internacoes.CBOR", "cbor.CBOR"],
        expected_result_type="data_quality_finding",
    ),
    DenseQuestion(
        id="DENSE_JOIN_018",
        question_pt="Auditoria: quantas internacoes tem etnia sem correspondencia na dimensao?",
        sql=(
            "SELECT COUNT(*) FILTER (WHERE e.ETNIA IS NULL) AS sem_correspondencia, "
            "COUNT(*) AS internacoes "
            "FROM internacoes i LEFT JOIN etnia e ON i.ETNIA = e.ETNIA"
        ),
        difficulty="L3",
        tables_used=["internacoes", "etnia"],
        columns_used=["internacoes.ETNIA", "etnia.ETNIA"],
        expected_result_type="data_quality_finding",
    ),
    DenseQuestion(
        id="DENSE_JOIN_019",
        question_pt="Como a tabela de staging se distribui por carater de internacao?",
        sql=(
            "SELECT c.DESCRICAO AS carater, COUNT(*) AS registros_staging "
            "FROM _staging_internacoes s JOIN car_int c ON s.CAR_INT = c.CAR_INT "
            "GROUP BY 1 ORDER BY registros_staging DESC"
        ),
        difficulty="L2",
        tables_used=["_staging_internacoes", "car_int"],
        columns_used=["_staging_internacoes.CAR_INT", "car_int.CAR_INT"],
        expected_result_type="distribution",
    ),
    DenseQuestion(
        id="DENSE_JOIN_020",
        question_pt="Quantos hospitais existem por UF do municipio do hospital?",
        sql=(
            "SELECT m.SG_UF, COUNT(*) AS hospitais "
            "FROM hospital h JOIN municipios m ON h.MUNIC_MOV = m.CO_MUNICIPIO_6D "
            "GROUP BY 1 ORDER BY hospitais DESC"
        ),
        difficulty="L2",
        tables_used=["hospital", "municipios"],
        columns_used=["hospital.MUNIC_MOV", "municipios.CO_MUNICIPIO_6D", "municipios.SG_UF"],
        expected_result_type="distribution",
        data_quality_notes="No banco atual a tabela hospital esta vazia.",
    ),
    DenseQuestion(
        id="DENSE_JOIN_021",
        question_pt="Qual populacao socioeconomica existe por UF e ano quando ha denominador socioeconomico?",
        sql=(
            "SELECT m.SG_UF, se.NU_ANO AS ano, SUM(se.QT_POPULACAO) AS populacao "
            "FROM socioeconomico se JOIN municipios m ON se.CO_MUNICIPIO_6D = m.CO_MUNICIPIO_6D "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        difficulty="L3",
        tables_used=["socioeconomico", "municipios"],
        columns_used=["socioeconomico.CO_MUNICIPIO_6D", "municipios.CO_MUNICIPIO_6D", "socioeconomico.QT_POPULACAO"],
        expected_result_type="time_series",
        data_quality_notes="No banco atual a tabela socioeconomico esta vazia.",
    ),
    DenseQuestion(
        id="DENSE_JOIN_022",
        question_pt="Quantas mortes hospitalares com diagnostico principal CID C ocorreram por ano?",
        sql=(
            "SELECT year(i.DT_INTER) AS ano, COUNT(*) AS mortes_cid_c "
            "FROM internacoes i JOIN cid c ON i.DIAG_PRINC = c.CID "
            "WHERE i.MORTE AND c.CID LIKE 'C%' "
            "GROUP BY 1 ORDER BY 1"
        ),
        difficulty="L3",
        tables_used=["internacoes", "cid"],
        columns_used=["internacoes.DIAG_PRINC", "internacoes.MORTE", "cid.CID"],
        expected_result_type="time_series",
        assumptions="Proxy de neoplasia maligna por CID-10 iniciando com C no diagnostico principal.",
    ),
    DenseQuestion(
        id="DENSE_JOIN_023",
        question_pt="Qual e a taxa de mortalidade hospitalar por sexo?",
        sql=(
            "SELECT s.DESCRICAO AS sexo, COUNT(*) AS internacoes, "
            "COUNT(*) FILTER (WHERE i.MORTE) AS mortes, "
            "ROUND(100.0 * COUNT(*) FILTER (WHERE i.MORTE) / COUNT(*), 4) AS taxa_morte_pct "
            "FROM internacoes i JOIN sexo s ON i.SEXO = s.SEXO "
            "GROUP BY 1 ORDER BY taxa_morte_pct DESC"
        ),
        difficulty="L3",
        tables_used=["internacoes", "sexo"],
        columns_used=["internacoes.SEXO", "internacoes.MORTE", "sexo.SEXO"],
        expected_result_type="distribution",
    ),
    DenseQuestion(
        id="DENSE_JOIN_024",
        question_pt="Quais UFs e sexos tiveram mais internacoes por residencia mapeada?",
        sql=(
            "SELECT m.SG_UF, s.DESCRICAO AS sexo, COUNT(*) AS internacoes "
            "FROM internacoes i "
            "JOIN municipios m ON i.MUNIC_RES = m.CO_MUNICIPIO_6D "
            "JOIN sexo s ON i.SEXO = s.SEXO "
            "GROUP BY 1, 2 ORDER BY internacoes DESC LIMIT 20"
        ),
        difficulty="L4",
        tables_used=["internacoes", "municipios", "sexo"],
        columns_used=["internacoes.MUNIC_RES", "internacoes.SEXO", "municipios.SG_UF", "sexo.DESCRICAO"],
        expected_result_type="ranking",
        assumptions="Restrito a internacoes com municipio de residencia mapeado.",
    ),
    DenseQuestion(
        id="DENSE_JOIN_025",
        question_pt="Qual e o mix de complexidade por carater de internacao?",
        sql=(
            "SELECT comp.DESCRICAO AS complexidade, car.DESCRICAO AS carater, COUNT(*) AS internacoes "
            "FROM internacoes i "
            "JOIN complexidade comp ON i.COMPLEX = comp.COMPLEX "
            "JOIN car_int car ON i.CAR_INT = car.CAR_INT "
            "GROUP BY 1, 2 ORDER BY internacoes DESC"
        ),
        difficulty="L4",
        tables_used=["internacoes", "complexidade", "car_int"],
        columns_used=["internacoes.COMPLEX", "internacoes.CAR_INT", "complexidade.DESCRICAO", "car_int.DESCRICAO"],
        expected_result_type="distribution",
    ),
]


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


def execute_question(con: duckdb.DuckDBPyConnection, question: DenseQuestion, evidence_dir: Path, db_path: Path) -> dict[str, Any]:
    start = time.perf_counter()
    cursor = con.execute(question.sql)
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    raw_rows = cursor.fetchall()
    duration = time.perf_counter() - start
    rows = [
        {columns[idx]: normalize_value(value) for idx, value in enumerate(raw)}
        for raw in raw_rows
    ]
    evidence = {
        "id": question.id,
        "question_pt": question.question_pt,
        "executed_at": datetime.now(UTC).isoformat(),
        "database_file": str(db_path),
        "sql": question.sql,
        "duration_seconds": round(duration, 6),
        "performance_class": "fast" if duration < 1 else "medium" if duration < 10 else "slow",
        "row_count": len(rows),
        "columns": columns,
        "preview_rows": rows[:50],
        "result_hash": result_hash(columns, rows),
        "semantic_disposition": "accepted",
    }
    evidence_path = evidence_dir / f"{question.id}.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=True, default=json_default),
        encoding="utf-8",
    )
    return {
        "row_count": len(rows),
        "result_summary": summarize_rows(rows),
        "duration_seconds": round(duration, 6),
        "evidence_path": evidence_path,
    }


def question_payload(question: DenseQuestion, execution: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": question.id,
        "persona": "Analista DATASUS/SIH",
        "question_pt": question.question_pt,
        "difficulty": question.difficulty,
        "sql": question.sql,
        "tables_used": question.tables_used,
        "columns_used": question.columns_used,
        "expected_result_type": question.expected_result_type,
        "execution_status": "passed",
        "row_count": execution["row_count"],
        "result_summary": execution["result_summary"],
        "validation_evidence": str(execution["evidence_path"]),
        "assumptions": question.assumptions,
        "data_quality_notes": question.data_quality_notes,
        "duration_seconds": execution["duration_seconds"],
        "created_at": datetime.now(UTC).date().isoformat(),
        "semantic_disposition": "accepted",
    }


def write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=True, default=json_default))
            handle.write("\n")


def main() -> int:
    cfg = load_config()
    out_dir = cfg.project_root / "evaluation/ground_truth"
    evidence_dir = out_dir / "dense_current_db_query_results"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(cfg.db_path), read_only=True)
    try:
        table_payloads = [
            question_payload(question, execute_question(con, question, evidence_dir, cfg.db_path))
            for question in TABLE_QUESTIONS
        ]
        join_payloads = [
            question_payload(question, execute_question(con, question, evidence_dir, cfg.db_path))
            for question in JOIN_QUESTIONS
        ]
    finally:
        con.close()

    combined = table_payloads + join_payloads
    write_jsonl(out_dir / "dense_current_db_tables.jsonl", table_payloads)
    write_jsonl(out_dir / "dense_current_db_joins.jsonl", join_payloads)
    write_jsonl(out_dir / "dense_current_db_all.jsonl", combined)

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "db_path": str(cfg.db_path),
        "table_questions": len(table_payloads),
        "join_questions": len(join_payloads),
        "total_questions": len(combined),
        "files": {
            "tables": str(out_dir / "dense_current_db_tables.jsonl"),
            "joins": str(out_dir / "dense_current_db_joins.jsonl"),
            "all": str(out_dir / "dense_current_db_all.jsonl"),
            "evidence_dir": str(evidence_dir),
        },
    }
    (out_dir / "dense_current_db_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
