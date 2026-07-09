# Plano de Ablation e Baseline OpenAI API

## Objetivo

Implementar uma avaliacao sistematica para medir quanto cada componente do
agente Text-to-SQL agrega em qualidade, robustez, latencia e custo, comparando o
pipeline atual com variantes de ablation e com baselines que chamam diretamente
a OpenAI API para gerar SQL.

O resultado esperado e um runner reproduzivel que responda, com evidencia
quantitativa:

- o agente completo melhora a acuracia de resultado em relacao a um prompt
  direto na OpenAI API?
- quais componentes do agente mais contribuem para qualidade?
- quais componentes aumentam custo/latencia sem ganho proporcional?
- em quais familias de perguntas o baseline direto supera o agente?
- quais classes de erro aparecem quando removemos catalogo, contexto,
  self-correction ou outras camadas?

Esta avaliacao deve focar apenas em Text-to-SQL e resposta tabular/escalar. A
avaliacao de graficos fica fora do escopo deste plano.

## Escopo

Incluido:

- Runner de ablation por variantes do agente.
- Baseline direto com OpenAI API para geracao de SQL.
- Comparacao por resultado executado no DuckDB.
- Comparacao por dificuldade, tema, tipo de resultado e classe de erro.
- Relatorios em JSON, CSV, JSONL e Markdown.
- Checks de regressao automatizaveis.
- Testes unitarios para contratos e estrategias.

Fora do escopo:

- Avaliacao de graficos.
- Avaliacao de frontend.
- Fine-tuning.
- Treinamento de modelos.
- Benchmark externo como Spider/BIRD.
- Execucao de SQL gerada sem validacao minima.

## Principios de Design

1. **Mesma metrica para todos**
   - O agente completo, variantes de ablation e baselines OpenAI devem passar
     pelo mesmo processo de execucao e comparacao.
   - A comparacao primaria deve continuar sendo resultado executado, nao match
     textual de SQL.

2. **Sem duplicacao do avaliador atual**
   - Reutilizar a logica de `evaluation/chatbot/evaluate_extraction_accuracy.py`
     sempre que possivel.
   - Extrair funcoes comuns para modulos compartilhados antes de adicionar novos
     runners grandes.

3. **Execucao segura**
   - Toda SQL gerada, inclusive pelo baseline direto OpenAI, deve passar por
     validacao read-only antes de executar.
   - SQL invalida ou insegura deve ser registrada como falha de validacao, nao
     executada.

4. **Variantes configuraveis**
   - Ablations devem ser descritas por configuracao, nao por forks de codigo.
   - Cada variante deve declarar explicitamente quais componentes estao ativos.

5. **Reprodutibilidade**
   - Cada run deve registrar dataset, modelo, configuracao, git SHA, timestamp,
     variaveis relevantes, limites e seeds quando existirem.

6. **Observabilidade por pergunta**
   - Alem do resumo agregado, cada pergunta deve gerar um registro completo com
     SQL, status, erros, tabelas recuperadas, variante, latencia e comparacao.

## Datasets

Usar os datasets existentes como base:

| Dataset | Uso |
|---|---|
| `evaluation/ground_truth/stage1_questions_v2.jsonl` | Smoke/regressao rapida |
| `evaluation/ground_truth/ground_truth_228_validated.jsonl` | Avaliacao principal |
| `evaluation/ground_truth/dense_current_db_all.jsonl` | Stress no banco atual |
| `evaluation/ground_truth/cid_disease_tooling_eval.jsonl` | Avaliacao focada em CID/doencas |

Criar um manifesto opcional para suites de ablation:

```text
evaluation/chatbot/ablation_suites.json
```

Exemplo:

```json
{
  "smoke_30": {
    "dataset": "evaluation/ground_truth/ground_truth_228_validated.jsonl",
    "ids": ["GT001", "GT002"],
    "description": "Suite curta e estratificada para iteracao local"
  },
  "gt228_full": {
    "dataset": "evaluation/ground_truth/ground_truth_228_validated.jsonl",
    "description": "Suite principal completa"
  }
}
```

## Variantes de Ablation

### V0: `full_agent`

Pipeline atual completo.

Configuracao:

- Pydantic AI habilitado.
- Schema/context retrieval atual.
- Context enrichment habilitado.
- Catalog tools habilitadas.
- Self-correction habilitado.
- Multi-candidate conforme configuracao escolhida para o run.
- Answer synthesis pode ficar fora da metrica primaria, pois o avaliador mede
  SQL executada e resultado.

### V1: `no_catalog_tools`

Remove tool calling de catalogo e candidatos de catalogo.

Objetivo:

- Medir impacto de CID, procedimentos e valores de dimensao no resultado.

Configuracao:

```env
CHATBOT_CATALOG_TOOLS_ENABLED=false
```

Tambem deve impedir enriquecimento por catalog candidates se a variante exigir
um desligamento completo do catalogo.

Metricas esperadas:

- queda em perguntas de doencas/CID;
- queda em perguntas de procedimentos;
- aumento de filtros textuais incorretos;
- aumento de erros de schema/value linking.

### V2: `no_context_enrichment`

Mantem retrieval de schema, mas remove enriquecimentos adicionais:

- few-shot examples;
- value hints;
- contexto relacionado de audit log;
- metric rules injetadas fora do schema basico, se estiverem em camada
  separavel.

Objetivo:

- Medir se contexto adicional melhora generalizacao ou causa overfitting.

Implementacao desejada:

- Criar flag interna `EvaluationFeatureFlags.context_enrichment_enabled`.
- O runner injeta a flag na estrategia, sem editar prompts globalmente.

### V3: `no_self_correction`

Desliga refiner e retry de SQL.

Objetivo:

- Medir quanto o loop de validacao/execucao/correcao melhora sucesso final.

Configuracao:

```env
CHATBOT_SQL_CORRECTION_ATTEMPTS=0
```

Metricas esperadas:

- menor `sql_execution_rate`;
- maior `validation_failed_rate`;
- mais erros de tabela/coluna/join que seriam corrigiveis.

### V4: `single_candidate`

Forca uma unica SQL candidata.

Objetivo:

- Medir impacto de multi-candidate generation e ranking quando esse modo estiver
  habilitado no run principal.

Configuracao:

```env
CHATBOT_ENABLE_MULTI_CANDIDATE=false
CHATBOT_SQL_CANDIDATES=1
```

### V5: `multi_candidate`

Forca multiplas candidatas para comparar com `single_candidate`.

Objetivo:

- Medir ganho real de gerar varias SQLs e ranquear por execucao/heuristica.

Configuracao:

```env
CHATBOT_ENABLE_MULTI_CANDIDATE=true
CHATBOT_SQL_CANDIDATES=3
```

### V6: `keyword_schema_only`

Forca retrieval simples por keyword.

Objetivo:

- Medir se o modo de schema retrieval mais simples e suficiente.

Configuracao:

```env
CHATBOT_SCHEMA_RETRIEVAL_MODE=keyword
```

### V7: `llamaindex_schema_retrieval`

Usa LlamaIndex apenas para schema retrieval, mantendo o resto do pipeline.

Objetivo:

- Medir se LlamaIndex agrega no contexto atual em relacao ao modo `auto` ou
  `keyword`.

Configuracao:

```env
CHATBOT_SCHEMA_RETRIEVAL_MODE=llamaindex_vector
```

### V8: `no_llm_generation`

Desliga geracao por LLM.

Objetivo:

- Baseline deterministico/debug para confirmar quanto o sistema depende do LLM.
- Nao deve ser interpretado como concorrente real, mas como controle negativo.

Configuracao:

- `allow_llm=false` na estrategia.

## Baselines Diretos com OpenAI API

Os baselines diretos devem testar o que acontece quando removemos o workflow
agentico e usamos a OpenAI API para gerar SQL a partir de um prompt.

Todos os baselines devem:

- usar o mesmo dataset;
- receber a mesma pergunta;
- gerar uma unica SQL;
- passar por `sql_validator.validate_sql`;
- executar somente se a SQL for validada;
- comparar com o mesmo mecanismo usado pelo agente.

### B0: `openai_raw_minimal_schema`

Prompt direto com:

- instrucao Text-to-SQL;
- lista curta de tabelas e colunas relevantes ou catalogo resumido;
- regras basicas de seguranca;
- pergunta do usuario.

Objetivo:

- Medir uma chamada direta pouco assistida.

Risco esperado:

- alta taxa de tabela/coluna inventada;
- dificuldade com joins;
- dificuldade com CID/procedimentos.

### B1: `openai_raw_retrieved_schema`

Prompt direto com:

- pergunta;
- mesmo `RetrievedContext` usado pelo agente;
- schema context renderizado;
- sem catalog tools;
- sem self-correction;
- sem workflow multi-etapas.

Objetivo:

- Isolar o ganho do workflow sobre um baseline que ja recebe bom contexto.

Essa e a comparacao mais justa para responder:

> O agente agrega alem de passar contexto para o modelo?

### B2: `openai_raw_full_context`

Prompt direto com:

- `RetrievedContext`;
- regras de dominio principais;
- exemplos few-shot recuperados;
- value hints;
- catalog candidates pre-recuperados deterministicamente.

Objetivo:

- Medir se um prompt rico em uma chamada unica compete com o agente completo.

Interpretacao:

- Se esse baseline chegar perto do agente, precisamos revisar se o workflow esta
  agregando pouco.
- Se ele falhar em repair/execucao, isso valida self-correction e validacao
  iterativa.

### B3: `openai_raw_one_retry`

Prompt direto com uma tentativa de correcao apos erro de validacao ou execucao.

Objetivo:

- Comparar um loop simples de retry com o refiner estruturado do agente.

Limite:

- Apenas uma tentativa.
- O retry recebe erro e SQL anterior.
- A SQL corrigida tambem passa por validacao antes de executar.

## Arquitetura Proposta

Criar um pacote de avaliacao compartilhado:

```text
evaluation/chatbot/ablation/
|-- __init__.py
|-- runner.py
|-- variants.py
|-- strategies.py
|-- baseline_openai.py
|-- metrics.py
|-- reports.py
`-- contracts.py
```

### `contracts.py`

Definir contratos pequenos e explicitos:

```python
@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    difficulty: str | None
    expected_sql: str
    expected_result_type: str
    metadata: dict[str, Any]

@dataclass(frozen=True)
class VariantSpec:
    name: str
    kind: Literal["agent", "openai_baseline", "control"]
    description: str
    config_overrides: dict[str, Any]
    feature_flags: dict[str, bool]

@dataclass
class StrategyResult:
    variant: str
    case_id: str
    generated_sql: str | None
    plan_source: str
    validation_status: str
    execution_status: str
    columns: list[str]
    rows: list[list[Any]]
    error_category: str | None
    error_message: str | None
    latency_seconds: float
    token_usage: dict[str, Any] | None
    cost_usd: float | None
    debug: dict[str, Any]
```

### `strategies.py`

Definir uma interface unica:

```python
class EvaluationStrategy(Protocol):
    name: str

    def run_case(self, case: EvalCase, context: SharedEvalContext) -> StrategyResult:
        ...
```

Estrategias:

- `PydanticAgentStrategy`
- `OpenAIDirectStrategy`
- `NoLlmControlStrategy`

O runner nao deve saber como cada estrategia gera SQL. Ele so chama
`run_case`.

### `variants.py`

Centralizar definicao das variantes:

```python
VARIANTS = {
    "full_agent": VariantSpec(...),
    "no_catalog_tools": VariantSpec(...),
    "no_self_correction": VariantSpec(...),
    "openai_raw_retrieved_schema": VariantSpec(...),
}
```

Evitar espalhar `if variant == ...` pelo runner.

### `baseline_openai.py`

Responsavel apenas pelos baselines diretos.

Funcoes:

- montar prompt;
- chamar OpenAI API;
- parsear SQL;
- opcionalmente coletar token usage;
- fazer uma tentativa de retry no baseline `openai_raw_one_retry`.

Nao deve executar SQL diretamente. A execucao fica no caminho compartilhado.

### `metrics.py`

Reutilizar ou mover funcoes do avaliador atual:

- canonicalizacao de resultado;
- comparacao scalar/ordered/unordered;
- shape match;
- alias-only difference;
- type-only difference;
- order-only mismatch;
- error categorization.

Ideal:

- extrair do `evaluate_extraction_accuracy.py` para um modulo comum;
- manter o script antigo funcionando chamando esse modulo.

### `reports.py`

Gerar:

- `summary.json`;
- `summary.csv`;
- `analysis.md`;
- `trace.jsonl`;
- `failures/*.jsonl`;
- matriz de comparacao por variante.

## Runner CLI

Criar:

```text
evaluation/chatbot/run_ablation.py
```

Interface:

```bash
.venv/bin/python evaluation/chatbot/run_ablation.py \
  --dataset evaluation/ground_truth/ground_truth_228_validated.jsonl \
  --variants full_agent,no_catalog_tools,no_self_correction,openai_raw_retrieved_schema \
  --run-id ablation_v1 \
  --limit 30
```

Opcoes:

| Flag | Uso |
|---|---|
| `--dataset` | Caminho do dataset JSONL |
| `--suite` | Nome de suite em `ablation_suites.json` |
| `--variants` | Lista de variantes |
| `--run-id` | ID de saida |
| `--limit` | Limite local para smoke |
| `--ids` | Lista explicita de IDs |
| `--fail-fast` | Para no primeiro erro inesperado |
| `--max-workers` | Paralelismo futuro, default 1 |
| `--no-openai-baselines` | Roda apenas variantes do agente |
| `--cache-openai` | Reusa geracoes OpenAI do cache |
| `--overwrite` | Sobrescreve run existente |

## Estrutura de Saida

```text
evaluation/chatbot/results/ablation_v1/
|-- run_config.json
|-- summary.json
|-- summary.csv
|-- analysis.md
|-- trace.jsonl
|-- variants/
|   |-- full_agent/
|   |   |-- results.json
|   |   `-- trace.jsonl
|   |-- no_catalog_tools/
|   |   |-- results.json
|   |   `-- trace.jsonl
|   `-- openai_raw_retrieved_schema/
|       |-- results.json
|       `-- trace.jsonl
`-- failures/
    |-- full_agent_wins.jsonl
    |-- baseline_wins.jsonl
    |-- regressions_vs_full_agent.jsonl
    |-- validation_failures.jsonl
    `-- execution_failures.jsonl
```

## Metricas

### Metricas Primarias

| Metrica | Definicao |
|---|---|
| `result_match_rate` | Resultado executado bate com ground truth |
| `sql_valid_rate` | SQL gerada passou validacao |
| `sql_execution_rate` | SQL validada executou no DuckDB |
| `shape_match_rate` | Shape de colunas/linhas bate com esperado |
| `value_match_rate` | Valores batem ignorando aliases quando aplicavel |

### Metricas Secundarias

| Metrica | Definicao |
|---|---|
| `alias_only_difference_rate` | Resultado correto com alias diferente |
| `order_only_mismatch_rate` | Valores certos com ordenacao errada |
| `avg_latency_seconds` | Latencia media por pergunta |
| `p50_latency_seconds` | Mediana |
| `p95_latency_seconds` | Percentil 95 |
| `avg_tokens_per_query` | Media de tokens quando disponivel |
| `estimated_cost_usd` | Custo estimado quando usage existir |

### Metricas por Fatia

Agregar por:

- variante;
- dificuldade;
- `expected_result_type`;
- tema inferido do ID/dataset;
- tabelas esperadas;
- perguntas com CID/doenca;
- perguntas com procedimentos;
- perguntas com joins;
- perguntas com geografia;
- perguntas temporais.

## Categorias de Erro

Padronizar categorias para comparacao:

| Categoria | Exemplo |
|---|---|
| `invalid_sql` | Parse/statement invalido |
| `unsafe_sql` | Mutating SQL, multiplas statements, arquivo externo |
| `missing_table` | Tabela inexistente |
| `missing_column` | Coluna inexistente |
| `schema_linking_error` | Usou tabela/coluna errada |
| `join_error` | Join ausente, duplicador ou chave errada |
| `filter_error` | Filtro incorreto |
| `metric_error` | Agregacao ou denominador errado |
| `shape_error` | Colunas/linhas diferentes do contrato esperado |
| `order_error` | Ordenacao errada |
| `execution_error` | DuckDB falhou apos validacao |
| `timeout` | Tempo excedido |
| `unknown` | Falha nao classificada |

## OpenAI Direct Baseline: Prompt Contract

O prompt do baseline deve ser versionado em codigo e salvo no run config.

Requisitos:

- pedir somente SQL;
- proibir markdown;
- proibir DDL/DML;
- proibir multiplas statements;
- explicar que o dialeto e DuckDB;
- incluir row limit quando a pergunta for exploratoria;
- instruir a usar apenas tabelas/colunas do contexto;
- instruir a retornar `SELECT` ou `WITH`.

Exemplo conceitual:

```text
Voce gera SQL DuckDB read-only para responder perguntas sobre SIH/SUS.
Retorne apenas uma query SQL. Use somente tabelas e colunas listadas abaixo.
Nunca use INSERT, UPDATE, DELETE, DROP, COPY, INSTALL, LOAD ou acesso a arquivos.

Contexto do schema:
...

Pergunta:
...
```

Parsing:

- remover fences ```sql se vierem;
- rejeitar texto com mais de uma query;
- validar com o validador existente;
- se falhar, registrar erro.

## Checkpoints de Implementacao

### Checkpoint 1: Refatorar nucleo de avaliacao compartilhado

Objetivo:

- Extrair comparacao, execucao de ground truth, canonicalizacao e resumo do
  avaliador atual para modulos reutilizaveis.

Arquivos esperados:

```text
evaluation/chatbot/eval_core/
|-- __init__.py
|-- dataset.py
|-- execution.py
|-- comparison.py
|-- error_taxonomy.py
`-- summaries.py
```

Criterios de aceite:

- `evaluation/chatbot/evaluate_extraction_accuracy.py` continua funcionando.
- Testes existentes continuam passando.
- Nenhuma logica grande duplicada no novo runner.

### Checkpoint 2: Criar contratos e variantes

Objetivo:

- Definir `EvalCase`, `VariantSpec`, `StrategyResult` e registry de variantes.

Arquivos esperados:

```text
evaluation/chatbot/ablation/contracts.py
evaluation/chatbot/ablation/variants.py
tests/test_ablation_variants.py
```

Criterios de aceite:

- todas as variantes tem nome unico;
- variantes invalidas geram erro claro;
- variantes declaram se usam OpenAI baseline ou agente;
- config overrides sao serializaveis em JSON.

### Checkpoint 3: Implementar `PydanticAgentStrategy`

Objetivo:

- Rodar o agente completo e variantes internas sem duplicar workflow.

Regras:

- usar `load_config` e `load_stage1_context`;
- aplicar overrides de forma local ao run, sem mutar ambiente global quando
  possivel;
- desligar componentes por flags ou config clara;
- registrar debug suficiente para analise.

Criterios de aceite:

- `full_agent` reproduz resultados do avaliador atual em uma suite pequena;
- `no_self_correction` realmente nao chama refiner;
- `no_catalog_tools` nao registra tool calls de catalogo;
- falhas sao registradas sem derrubar o run inteiro.

### Checkpoint 4: Implementar `OpenAIDirectStrategy`

Objetivo:

- Criar baselines diretos com OpenAI API.

Arquivos esperados:

```text
evaluation/chatbot/ablation/baseline_openai.py
tests/test_openai_baseline_prompt.py
```

Criterios de aceite:

- prompt e parse de SQL testados sem chamada real de rede;
- fences markdown sao removidos corretamente;
- respostas sem SQL sao rejeitadas com erro claro;
- SQL insegura nao executa;
- usage/custo sao coletados quando disponiveis.

### Checkpoint 5: Implementar runner CLI

Objetivo:

- Orquestrar dataset x variantes x perguntas.

Arquivo esperado:

```text
evaluation/chatbot/run_ablation.py
```

Criterios de aceite:

- suporta `--dataset`, `--variants`, `--run-id`, `--limit`, `--ids`;
- cria estrutura de saida completa;
- salva `run_config.json`;
- permite reexecutar com `--overwrite`;
- tem progresso legivel no terminal;
- retorna exit code diferente de zero apenas para erro operacional, nao para
  match baixo.

### Checkpoint 6: Relatorios e analise

Objetivo:

- Gerar analise util para decisao de arquitetura.

Arquivos esperados:

```text
evaluation/chatbot/ablation/reports.py
tests/test_ablation_reports.py
```

Relatorios:

- ranking de variantes por `result_match_rate`;
- delta vs `full_agent`;
- delta vs melhor baseline OpenAI;
- falhas por categoria;
- perguntas em que baseline ganhou do agente;
- perguntas em que agente ganhou do baseline;
- custo/latencia por variante;
- recomendacoes automaticas simples.

### Checkpoint 7: Smoke real

Objetivo:

- Rodar avaliacao pequena com LLM real e banco real.

Comando:

```bash
.venv/bin/python evaluation/chatbot/run_ablation.py \
  --dataset evaluation/ground_truth/stage1_questions_v2.jsonl \
  --variants full_agent,no_catalog_tools,no_self_correction,openai_raw_retrieved_schema \
  --limit 10 \
  --run-id ablation_smoke_10
```

Criterios de aceite:

- run completa;
- todas as variantes geram resultados;
- `summary.json`, `summary.csv`, `analysis.md` e `trace.jsonl` existem;
- nenhuma SQL insegura e executada;
- resultados sao interpretaveis.

### Checkpoint 8: Suite principal

Objetivo:

- Rodar suite mais representativa.

Comando:

```bash
.venv/bin/python evaluation/chatbot/run_ablation.py \
  --dataset evaluation/ground_truth/ground_truth_228_validated.jsonl \
  --variants full_agent,no_catalog_tools,no_context_enrichment,no_self_correction,openai_raw_minimal_schema,openai_raw_retrieved_schema,openai_raw_full_context,openai_raw_one_retry \
  --run-id ablation_gt228_v1
```

Criterios de aceite:

- relatorio final com deltas;
- lista de casos em que baseline direto venceu;
- lista de regressions causadas por cada ablation;
- custo e latencia estimados;
- recomendacao clara de quais componentes manter, revisar ou remover.

## Testes Necessarios

### Unitarios

Criar testes para:

- load de dataset;
- selecao por `--ids`;
- registry de variantes;
- aplicacao de config overrides;
- prompt do baseline OpenAI;
- extracao de SQL de respostas com e sem markdown;
- rejeicao de SQL insegura;
- canonicalizacao de resultados;
- comparacao scalar/ordered/unordered;
- categorizacao de erro;
- geracao de summary;
- escrita de artefatos.

Exemplos:

```text
tests/test_ablation_contracts.py
tests/test_ablation_variants.py
tests/test_ablation_openai_baseline.py
tests/test_ablation_runner.py
tests/test_ablation_reports.py
```

### Integracao sem LLM

Usar doubles/fakes para estrategias:

- `FakeSuccessStrategy`;
- `FakeInvalidSqlStrategy`;
- `FakeExecutionErrorStrategy`;
- `FakeSlowStrategy`.

Validar:

- runner nao quebra quando uma variante falha;
- artefatos sao gerados;
- summary agrega corretamente;
- failures JSONL contem os casos certos.

### Integracao com DuckDB temporario

Criar banco pequeno em `tmp_path` com uma ou duas tabelas.

Validar:

- SQL validada executa;
- SQL mutante e bloqueada;
- comparacao com ground truth funciona;
- baseline fake passa pelo mesmo executor.

### Smoke com OpenAI real

Marcador pytest ou script manual:

```bash
.venv/bin/python evaluation/chatbot/run_ablation.py \
  --dataset evaluation/ground_truth/stage1_questions_v2.jsonl \
  --variants full_agent,openai_raw_retrieved_schema \
  --limit 3 \
  --run-id openai_baseline_smoke_3
```

Esse smoke deve ser opcional e depender de `OPENAI_API_KEY`.

## Validacao de Resultado

Uma implementacao so deve ser considerada pronta quando:

1. `pytest -q` passa.
2. O runner roda com fakes sem OpenAI.
3. O runner roda com DuckDB temporario.
4. O runner roda uma suite real pequena com `full_agent`.
5. O runner roda uma suite real pequena com ao menos um baseline OpenAI.
6. Nenhuma SQL insegura e executada nos testes.
7. Os relatorios conseguem responder:
   - qual variante venceu;
   - qual componente mais impactou;
   - onde o baseline direto venceu;
   - quais erros aumentaram em cada ablation.

## Checks de Codigo Limpo

### Sem duplicacao

- Nao copiar o conteudo de `evaluate_extraction_accuracy.py` para o novo runner.
- Extrair funcoes comuns antes de reutilizar.
- O runner deve chamar estrategias por interface, nao por blocos gigantes de
  `if/else`.
- Prompt builders do baseline devem ser funcoes pequenas e testaveis.
- Comparacao de resultado deve existir em um unico lugar.

### Separacao de responsabilidades

| Modulo | Pode fazer | Nao deve fazer |
|---|---|---|
| `runner.py` | Orquestrar casos e variantes | Montar prompts OpenAI detalhados |
| `baseline_openai.py` | Gerar SQL por OpenAI direta | Executar SQL no DuckDB |
| `strategies.py` | Adaptar agente/baseline ao contrato | Gerar relatorio final |
| `metrics.py` | Agregar metricas | Ler `.env` ou chamar OpenAI |
| `reports.py` | Escrever relatorios | Rodar avaliacao |
| `eval_core/execution.py` | Executar SQL validada | Gerar SQL |
| `eval_core/comparison.py` | Comparar resultados | Chamar LLM |

### Tipagem e contratos

- Usar dataclasses ou Pydantic models para payloads principais.
- Evitar `dict[str, Any]` fora das bordas de I/O.
- Serializacao deve ser centralizada.
- Erros esperados devem virar `StrategyResult`, nao excecoes soltas.

### Configuracao

- Variantes devem ser declarativas.
- Config overrides devem ser aplicados por copia de `ChatbotConfig`, usando
  `dataclasses.replace`.
- Evitar mutar `os.environ` dentro do runner.
- Se uma variante exigir ambiente, registrar isso em `run_config.json`.

### Custos e rede

- Baselines OpenAI devem ter limite de dataset por default no smoke.
- Implementar cache opcional de geracoes OpenAI por hash de:
  - variante;
  - modelo;
  - prompt;
  - pergunta;
  - schema context.
- Nunca cachear API key.

### Segurança

- Nunca executar SQL sem `validate_sql`.
- Bloquear multiplas statements.
- Bloquear DDL/DML.
- Bloquear acesso a arquivos, extensoes, `COPY`, `INSTALL`, `LOAD`.
- Registrar SQL bloqueada como falha de seguranca/validacao.

## Ordem Recomendada

1. Refatorar nucleo comum de avaliacao.
2. Criar contratos e registry de variantes.
3. Implementar estrategia do agente completo.
4. Implementar runner com uma variante.
5. Implementar relatorios basicos.
6. Implementar baseline OpenAI minimo.
7. Adicionar baselines com contexto recuperado e contexto rico.
8. Adicionar ablations de catalogo, self-correction e contexto.
9. Rodar smoke 10.
10. Rodar suite 30 estratificada.
11. Rodar GT228 completo.
12. Revisar resultados e decidir proximas melhorias do agente.

## Decisoes que Devem Ficar Explicitas no PR

- Qual dataset foi usado como smoke.
- Quais variantes entram no primeiro release.
- Qual modelo OpenAI foi usado nos baselines.
- Se multi-candidate fica ligado ou desligado no `full_agent` padrao.
- Se `openai_raw_full_context` recebe catalog candidates deterministas ou nao.
- Como custo estimado e calculado.
- Quais thresholds, se houver, bloqueiam CI.

## Resultado Final Esperado

Ao final da implementacao, o projeto deve permitir comandos como:

```bash
.venv/bin/python evaluation/chatbot/run_ablation.py \
  --suite smoke_30 \
  --variants full_agent,no_catalog_tools,no_self_correction,openai_raw_retrieved_schema \
  --run-id smoke_30_v1
```

E produzir um relatorio objetivo:

```text
full_agent: 89.0% result_match, 98.0% execution, 6.1s avg
openai_raw_retrieved_schema: 61.0% result_match, 82.0% execution, 3.4s avg
no_catalog_tools: -12.0 pp vs full_agent, erros concentrados em CID/doencas
no_self_correction: -6.0 pp vs full_agent, aumento de execution_error
```

Esse relatorio deve ser suficiente para orientar decisoes de arquitetura:

- manter componente;
- simplificar componente;
- remover componente;
- melhorar prompt/contexto;
- investir em catalogo, retrieval ou self-correction.
