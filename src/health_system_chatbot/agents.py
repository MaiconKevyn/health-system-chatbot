from __future__ import annotations

import functools
import threading
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
- A tabela fato e `internacao` (singular, uma linha por AIH/`N_AIH`).
- `internacao.MUNIC_RES` e um codigo municipal numerico; para filtrar por nome
  de cidade, faca join com `municipios` e filtre `municipios.NO_MUNICIPIO` e,
  se possivel, `SG_UF`.
- Estabelecimento de atendimento: `internacao.CNES -> hospital.CNES`; a
  geografia do hospital vem de `hospital.MUNIC_MOV -> municipios`.
- Procedimentos ficam em `internacao_procedimento` (ligado por `N_AIH`); para
  contar internacoes use `COUNT(DISTINCT N_AIH)` ou `EXISTS`.
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
- Um termo pode ser procedimento (`internacao_procedimento.PROC_REA`) ou
  diagnostico CID (`internacao.DIAG_PRINC`). Se a pergunta usar a descricao de
  um CID (ex.: "parto espontaneo cefalico" = CID O800), filtre
  `internacao.DIAG_PRINC`; nao aproxime por um grupo de procedimentos mais
  amplo. Se uma tool avisar que o termo corresponde a um CID ou que o grupo nao
  cobre os qualificadores da pergunta, siga o candidato mais especifico.
- Exemplos few-shot sao referencias estruturais condicionais, nunca requisitos.
  Use apenas exemplos cujo escopo seja compativel com o QuestionContract. A
  pergunta e as regras semanticas com proveniencia prevalecem sobre o exemplo.
- Nao copie LIMIT, suporte minimo, faixa, periodo, particao ou coluna de um
  exemplo quando esses requisitos nao estiverem explicitos no QuestionContract.
- Nao adicione descricao de dimensao apenas porque a dimensao foi recuperada. Se
  a pergunta pede codigo/codigos, retorne o codigo cru e as metricas pedidas.
- Nao retorne colunas usadas apenas como filtro constante, como `SG_UF = 'RS'`,
  salvo se o usuario pedir essa coluna na saida.
- Retorne os conceitos obrigatorios do QuestionContract. Colunas de suporte so
  devem ser adicionadas quando forem necessarias para interpretar ou auditar a
  metrica e devem ser marcadas como opcionais.
- Quando o prompt incluir [CHART PLAN], a SQL deve retornar colunas
  compativeis com o contrato visual: dimensao x, serie quando houver e metrica
  numerica. Nao sacrifique a resposta correta para gerar grafico; se houver
  conflito, preserve a semantica da pergunta e deixe caveat no plano.
- Em `ORDER BY` de ranking, distribuicao, percentual, taxa ou media, use
  desempate deterministico com as dimensoes legiveis retornadas quando houver
  empate na metrica ordenada; exemplo: `ORDER BY ano, percentual DESC,
  capitulo_cid ASC`.
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
required_columns lista apenas as colunas do resultado (aliases da dimensao x,
serie e metrica, ex.: ["ano", "total_partos"]). Nunca liste colunas de origem
ou de filtro (ex.: `municipios.SG_UF`, `internacao_procedimento.PROC_REA`).
"""


_PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _ensure_provider_config(config: ChatbotConfig, *, purpose: str) -> None:
    if config.llm_provider not in _PROVIDER_ENV_VARS:
        return
    ready = (
        config.has_openai_key if config.llm_provider == "openai" else config.has_anthropic_key
    )
    if not ready:
        env_var = _PROVIDER_ENV_VARS[config.llm_provider]
        raise RuntimeError(f"{env_var} is required for Pydantic AI {purpose}")


def _openai_model(config: ChatbotConfig):
    _ensure_provider_config(config, purpose="OpenAI generation")

    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIResponsesModel(
        config.llm_model,
        provider=OpenAIProvider(api_key=config.openai_api_key),
    )


def _openai_model_settings(config: ChatbotConfig) -> Any:
    from pydantic_ai.models.openai import OpenAIResponsesModelSettings

    settings = OpenAIResponsesModelSettings(
        temperature=0,
        timeout=float(config.query_timeout_seconds),
        openai_store=False,
    )
    if config.llm_reasoning_effort:
        settings["openai_reasoning_effort"] = config.llm_reasoning_effort
    return settings


def _anthropic_model(config: ChatbotConfig):
    _ensure_provider_config(config, purpose="Anthropic generation")

    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    return AnthropicModel(
        config.llm_model,
        provider=AnthropicProvider(api_key=config.anthropic_api_key),
    )


def _ollama_model(config: ChatbotConfig):
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.ollama import OllamaProvider

    return OpenAIChatModel(
        config.llm_model,
        provider=OllamaProvider(base_url=config.ollama_base_url, api_key=config.ollama_api_key),
    )


def _generic_model_settings(config: ChatbotConfig) -> Any:
    from pydantic_ai.settings import ModelSettings

    return ModelSettings(
        temperature=0,
        timeout=float(config.query_timeout_seconds),
        max_tokens=8192,
    )


def _create_model(config: ChatbotConfig):
    if config.llm_provider == "openai":
        return _openai_model(config)
    if config.llm_provider == "anthropic":
        return _anthropic_model(config)
    if config.llm_provider == "ollama":
        return _ollama_model(config)
    raise RuntimeError(f"Unsupported LLM provider: {config.llm_provider}")


_thread_state = threading.local()


def _build_model(config: ChatbotConfig):
    """Return this thread's model (and HTTP client) for ``config``.

    Every agent build used to create a new provider and httpx client, paying a
    fresh TLS handshake on each LLM call. ``run_sync`` drives a per-thread event
    loop, so the client is shared only within a thread: the SQL, refiner, chart
    and answer agents of a request, and later requests served by the same API
    worker thread, reuse one warm connection.
    """
    models = getattr(_thread_state, "models", None)
    if models is None:
        models = _thread_state.models = {}
    model = models.get(config)
    if model is None:
        model = models[config] = _create_model(config)
    return model


def _build_model_settings(config: ChatbotConfig) -> Any:
    if config.llm_provider == "openai":
        return _openai_model_settings(config)
    return _generic_model_settings(config)


@functools.lru_cache(maxsize=32)
def _ollama_model_supports_tools(base_url: str, model: str) -> bool:
    import httpx

    native_base = base_url.rstrip("/")
    if native_base.endswith("/v1"):
        native_base = native_base[: -len("/v1")]
    try:
        response = httpx.post(f"{native_base}/api/show", json={"model": model}, timeout=10.0)
        response.raise_for_status()
        capabilities = response.json().get("capabilities", [])
    except Exception:
        # Can't confirm capabilities (server down, model missing, etc). Fail
        # open so behavior matches today's default; a real incompatibility
        # will surface as a clear provider error instead of a silent downgrade.
        return True
    return "tools" in capabilities


def _supports_tool_calling(config: ChatbotConfig) -> bool:
    if config.llm_provider != "ollama":
        return True
    return _ollama_model_supports_tools(config.ollama_base_url, config.llm_model)


def _agent_output_type(output_type: Any, *, supports_tools: bool) -> Any:
    if supports_tools:
        return output_type

    from pydantic_ai import PromptedOutput

    return PromptedOutput(output_type)


def build_sql_plan_agent(config: ChatbotConfig):
    from pydantic_ai import Agent

    supports_tools = _supports_tool_calling(config)
    agent = Agent(
        _build_model(config),
        deps_type=ChatDeps,
        output_type=_agent_output_type(SqlPlan, supports_tools=supports_tools),
        instructions=SQL_PLAN_INSTRUCTIONS,
        model_settings=_build_model_settings(config),
        retries=2,
        name="health_system_sql_plan_agent",
    )
    if config.catalog_tools_enabled and supports_tools:
        from .tools.catalog_tools import register_catalog_tools

        register_catalog_tools(agent)
    return agent


def build_sql_refiner_agent(config: ChatbotConfig):
    from pydantic_ai import Agent

    return Agent(
        _build_model(config),
        deps_type=RefinerDeps,
        output_type=_agent_output_type(SqlPlan, supports_tools=_supports_tool_calling(config)),
        instructions=SQL_REFINER_INSTRUCTIONS,
        model_settings=_build_model_settings(config),
        retries=2,
        name="health_system_sql_refiner_agent",
    )


def build_chart_plan_agent(config: ChatbotConfig):
    from pydantic_ai import Agent

    return Agent(
        _build_model(config),
        deps_type=ChartDeps,
        output_type=_agent_output_type(ChartPlan, supports_tools=_supports_tool_calling(config)),
        instructions=CHART_PLAN_INSTRUCTIONS,
        model_settings=_build_model_settings(config),
        retries=2,
        name="health_system_chart_plan_agent",
    )


def build_answer_agent(config: ChatbotConfig):
    from pydantic_ai import Agent

    from .answer_synthesizer import NaturalAnswer

    return Agent(
        _build_model(config),
        deps_type=AnswerDeps,
        output_type=_agent_output_type(NaturalAnswer, supports_tools=_supports_tool_calling(config)),
        instructions=ANSWER_INSTRUCTIONS,
        model_settings=_build_model_settings(config),
        retries=2,
        name="health_system_answer_agent",
    )
