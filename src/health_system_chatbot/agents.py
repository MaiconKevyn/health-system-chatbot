from __future__ import annotations

from typing import Any

from .agent_deps import AnswerDeps, ChartDeps, ChatDeps, RefinerDeps
from .config import ChatbotConfig
from .models import SqlPlan
from .visualization.schema import ChartPlan


SQL_PLAN_INSTRUCTIONS = """
Voce e um agente Text-to-SQL para o banco local SIH/SUS em DuckDB.

Retorne exclusivamente um SqlPlan estruturado. Gere apenas SQL DuckDB read-only.
Use SELECT ou WITH. Nunca use comandos mutantes, acesso a arquivos, extensoes ou
multiplas statements.

Regras de dominio obrigatorias:
- Diferencie municipio de residencia (`internacoes.MUNIC_RES`) de municipio do
  hospital (`hospital.MUNIC_MOV`).
- Codigos municipais sao numericos; para filtrar por nome de cidade, faca join
  com `municipios` e filtre `municipios.NO_MUNICIPIO` e, se possivel, `SG_UF`.
- Declare metric_basis para contagens, mortalidade, permanencia e valores.
- Declare date_basis quando a pergunta tiver recorte temporal.
- Declare geography_basis quando houver geografia.
- Declare grain, especialmente quando usar `internacao_procedimento`.
- Nao invente tabelas ou colunas fora do contexto recuperado.
- Se a pergunta depender de codigo, grupo, capitulo, procedimento ou valor
  textual que nao esteja explicitamente resolvido no contexto, chame uma tool de
  catalogo antes de gerar SQL. Use os candidatos retornados pelas tools como
  fonte de verdade; nao invente codigos CID, codigos de procedimento ou valores
  de dimensao.
- Quando um candidato de catalogo trouxer filtro recomendado, use esse filtro
  salvo se a pergunta exigir outra interpretacao. Registre a decisao em
  catalog_decisions.
- Quando houver `EXEMPLO_EXATO`, use o mesmo padrao SQL e preserve o shape de
  saida: colunas, agregacoes, LIMIT, ORDER BY e colunas diagnosticas.
- Quando houver exemplo few-shot quase igual, preserve a semantica e as colunas
  diagnosticas do exemplo.
- Em checagens de qualidade territorial com UFs validas, inclua contagem de
  codigos `SG_UF` invalidos quando o contexto indicar essa necessidade.
- Em perguntas de intervalo temporal de indicadores/dimensoes auxiliares,
  retorne tambem `COUNT(*) AS registros` quando isso ajuda a interpretar tabela
  vazia ou cobertura temporal.
- Nao adicione descricao de dimensao apenas porque a dimensao foi recuperada. Se
  a pergunta pede codigo/codigos, retorne o codigo cru e as metricas pedidas.
- Nao retorne colunas usadas apenas como filtro constante, como `SG_UF = 'RS'`,
  salvo se o usuario pedir essa coluna na saida.
- Em rankings, medias, totais ou distribuicoes por grupo, inclua `COUNT(*) AS
  internacoes` quando o exemplo ou a regra de negocio usa esse denominador como
  coluna de suporte.
- Em comparacoes por ano entre dois ou mais grupos nomeados, prefira uma linha
  por ano e uma coluna de metrica para cada grupo comparado, salvo se o usuario
  pedir formato longo.
- Quando o prompt incluir [CHART PLAN], a SQL deve retornar colunas
  compativeis com o contrato visual: dimensao x, serie quando houver e metrica
  numerica. Nao sacrifique a resposta correta para gerar grafico; se houver
  conflito, preserve a semantica da pergunta e deixe caveat no plano.
- Em `ORDER BY` de ranking, distribuicao, percentual, taxa ou media, use
  desempate deterministico com as dimensoes legiveis retornadas quando houver
  empate na metrica ordenada; exemplo: `ORDER BY ano, percentual DESC,
  capitulo_cid ASC`.
- Para pergunta simples de mortes/obitos por ano, retorne apenas a base temporal
  e a contagem de mortes, salvo se a pergunta pedir taxa, denominador ou total
  de internacoes.
"""


SQL_REFINER_INSTRUCTIONS = """
Voce corrige um SqlPlan rejeitado para o banco SIH/SUS local.

Use os erros de validacao/execucao fornecidos como feedback. Retorne um novo
SqlPlan estruturado. Nunca tente contornar guardrails; corrija a SQL para passar
pela validacao deterministica e preservar a intencao da pergunta.
"""


ANSWER_INSTRUCTIONS = """
Voce sintetiza respostas de analise de dados de saude em portugues.

Use somente o resultado executado e os caveats fornecidos. Nao mostre SQL na
resposta final. Se houver truncamento, avise. Seja claro, curto e fiel aos dados.
"""


CHART_PLAN_INSTRUCTIONS = """
Voce planeja visualizacoes para um agente Text-to-SQL de saude.

Retorne exclusivamente um ChartPlan estruturado. Nao gere SQL. O plano deve
descrever qual shape a SQL precisa retornar para suportar a visualizacao:
dimensao x, metrica numerica, serie opcional e tipo de grafico preferido.
Se o usuario pediu apenas uma contagem escalar, use kpi. Para serie temporal,
prefira line. Para distribuicoes categoricas, prefira bar salvo pedido explicito
por pizza/rosca. Para muitas categorias, ainda planeje o shape correto; a camada
de renderizacao decide se cai para tabela.
"""


def _ensure_openai_config(config: ChatbotConfig, *, purpose: str) -> None:
    if config.llm_provider != "openai":
        raise RuntimeError(f"Unsupported LLM provider for {purpose}: {config.llm_provider}")
    if not config.has_openai_key:
        raise RuntimeError(f"OPENAI_API_KEY is required for Pydantic AI {purpose}")


def _openai_model(config: ChatbotConfig):
    _ensure_openai_config(config, purpose="OpenAI generation")

    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIResponsesModel(
        config.llm_model,
        provider=OpenAIProvider(api_key=config.openai_api_key),
    )


def _openai_model_settings(config: ChatbotConfig) -> Any:
    from pydantic_ai.models.openai import OpenAIResponsesModelSettings

    return OpenAIResponsesModelSettings(
        temperature=0,
        timeout=float(config.query_timeout_seconds),
        openai_store=False,
    )


def build_sql_plan_agent(config: ChatbotConfig):
    from pydantic_ai import Agent

    agent = Agent(
        _openai_model(config),
        deps_type=ChatDeps,
        output_type=SqlPlan,
        instructions=SQL_PLAN_INSTRUCTIONS,
        model_settings=_openai_model_settings(config),
        retries=2,
        name="health_system_sql_plan_agent",
    )
    if config.catalog_tools_enabled:
        from .tools.catalog_tools import register_catalog_tools

        register_catalog_tools(agent)
    return agent


def build_sql_refiner_agent(config: ChatbotConfig):
    from pydantic_ai import Agent

    return Agent(
        _openai_model(config),
        deps_type=RefinerDeps,
        output_type=SqlPlan,
        instructions=SQL_REFINER_INSTRUCTIONS,
        model_settings=_openai_model_settings(config),
        retries=2,
        name="health_system_sql_refiner_agent",
    )


def build_chart_plan_agent(config: ChatbotConfig):
    from pydantic_ai import Agent

    return Agent(
        _openai_model(config),
        deps_type=ChartDeps,
        output_type=ChartPlan,
        instructions=CHART_PLAN_INSTRUCTIONS,
        model_settings=_openai_model_settings(config),
        retries=2,
        name="health_system_chart_plan_agent",
    )


def build_answer_agent(config: ChatbotConfig):
    from pydantic_ai import Agent

    from .answer_synthesizer import NaturalAnswer

    return Agent(
        _openai_model(config),
        deps_type=AnswerDeps,
        output_type=NaturalAnswer,
        instructions=ANSWER_INSTRUCTIONS,
        model_settings=_openai_model_settings(config),
        retries=2,
        name="health_system_answer_agent",
    )
