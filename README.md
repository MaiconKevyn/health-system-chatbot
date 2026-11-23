# Datasus Health System Chatbot

[![Python](https://img.shields.io/badge/python-%3E%3D3.12-blue.svg)](https://www.python.org/)
[![Pydantic AI](https://img.shields.io/badge/Pydantic%20AI-%3E%3D2.6.0-e92063.svg)](https://ai.pydantic.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-%3E%3D0.115.0-009688.svg)](https://fastapi.tiangolo.com/)
[![DuckDB](https://img.shields.io/badge/DuckDB-%3E%3D1.5.2-fff000.svg)](https://duckdb.org/)
[![React](https://img.shields.io/badge/React-18.3.1-61dafb.svg)](https://react.dev/)
[![Apache ECharts](https://img.shields.io/badge/Apache%20ECharts-6.0.0-aa344d.svg)](https://echarts.apache.org/)

Datasus Health System Chatbot is a Text-to-SQL application for analytical
questions over a local SIH/SUS DuckDB database. It translates natural-language
questions into validated SQL, executes the query in read-only mode, and returns
a concise answer in Portuguese. When the user asks for a visualization, the
system can also return a structured chart payload rendered by the web frontend.

The project ships two chat engines behind one dispatcher
(`health_system_chatbot.chat.run_chat`), used by the REST API and by the `ask`
and `ask-file` CLI commands:

| Engine | When it runs | What it is |
|---|---|---|
| **SUS** (default) | `CHATBOT_CHAT_ENGINE=auto` with the OpenAI provider, or `CHATBOT_CHAT_ENGINE=sus` | The SIHRD9 engine ported from `MaiconKevyn/agent-text-to-sql-sus`: a curated data dictionary, value linking, one structured SQL plan, a repair loop and an answer prompt, all in [`src/health_system_chatbot/sus`](src/health_system_chatbot/sus). It reuses this project's SQL validator, DuckDB executor and chart contract. |
| **Legacy** | `CHATBOT_CHAT_ENGINE=legacy`, or `auto` with Anthropic, Ollama or LlamaIndex | The Pydantic AI workflow (`health_system_chatbot.workflow.run_chat`): context retrieval, catalog tools, typed SQL plans, semantic validation, self-correction, chart planning and answer synthesis. |

One backend serves the React UI (chat, ECharts, SQL/debug details, schema
explorer and database console) for both engines. The offline diagnostic
commands (`context`, `draft-sql`, `eval`) and the historical evaluation runners
use the legacy implementation. The sibling repository
`agent-text-to-sql-sus` remains a separate product with its own investigation
and dashboard UI.

## Contents

- [What This Project Is](#what-this-project-is)
- [Architecture](#architecture)
- [SUS Engine Workflow](#sus-engine-workflow)
- [Legacy Engine Workflow](#legacy-engine-workflow)
- [Pydantic AI Components](#pydantic-ai-components)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [API](#api)
- [Frontend](#frontend)
- [Evaluation](#evaluation)
- [Observability](#observability)

## What This Project Is

This repository implements a production-oriented chatbot for Brazilian public
health data analysis. The main workload is difficult Text-to-SQL over a large
local database: counts, rankings, mortality analysis, temporal series,
geographic filters, CID/procedure lookups, joins with descriptive dimensions,
and chart requests.

The system supports:

- Natural-language questions over the local SIH/SUS analytical database.
- Structured SQL plans: strict JSON schema in the SUS engine, typed Pydantic AI
  outputs in the legacy engine.
- Grounding in the data: a curated SIHRD9 dictionary with measured pitfalls
  (SUS engine) and local catalog tools for CID, procedure and dimension values
  (legacy engine).
- Deterministic, read-only SQL guardrails before execution (both engines).
- Execution feedback and repair for failed SQL.
- Natural-language answer synthesis separated from technical debug metadata.
- Optional chart generation with Apache ECharts-compatible payloads.
- CLI, FastAPI REST API, and React/Vite web frontend.
- Regression runners and a curated benchmark that compares engines and
  projects on the same questions.

## Architecture

The web frontend talks to the FastAPI backend. The backend and the CLI call the
same dispatcher, `chat.run_chat`, which picks the engine from
`CHATBOT_CHAT_ENGINE`:

```text
React UI / CLI ──► FastAPI /api/chat ──► chat.run_chat
                                           ├─ SUS (default):  sus.engine.ask
                                           └─ legacy:         workflow.run_chat
both engines ──► sql_validator.validate_sql ──► duckdb_executor (read-only) ──► answer + chart
```

Main layers:

| Layer | Responsibility |
|---|---|
| React/Vite frontend | Chat UI, debug mode, schema explorer, SQL display, chart rendering |
| FastAPI API | HTTP adapter for chat, schema, health, model info, and database explorer endpoints |
| Chat dispatcher | `chat.run_chat`: selects the engine and writes the trace and audit record |
| SUS engine | `sus/`: dictionary prompt, value linking, structured SQL plan, repair loop, answer prompt |
| Legacy workflow | `workflow.py`: classification, context retrieval, Pydantic AI agents, catalog tools, self-correction, chart planning |
| Validation layer | Read-only SQL checks, table/column checks, join policies, and safety constraints (shared) |
| DuckDB executor | Executes validated SQL against `sihrd9.duckdb` in read-only mode, with row limit and timeout (shared) |
| Visualization | Chart contract and ECharts options from the executed result (shared) |
| Evaluation layer | Ground truth, regression runners, benchmark harness, traces and reports |

The diagram below shows the legacy workflow in detail.

![Legacy workflow architecture](docs/assets/chatbot-architecture.svg)

## SUS Engine Workflow

Implemented in [`src/health_system_chatbot/sus/engine.py`](src/health_system_chatbot/sus/engine.py).

1. **Value linking**: `sus/value_linker.py` matches the question against CID
   codes written by the user (with or without the dot), CID descriptions,
   procedure names and municipality names, and passes the real codes it finds
   to the model as hints.
2. **SQL plan**: one OpenAI chat-completions call with a strict JSON schema
   returns `answerable`, `sql`, `assumptions`, `refusal` and a `chart` hint.
   The system prompt embeds the curated dictionary
   [`sus/sihrd9.yaml`](src/health_system_chatbot/sus/sihrd9.yaml): tables,
   columns, canonical joins and the measured pitfalls of this database (see
   [Database Notes](#database-notes)).
3. **Refusal**: when the plan says the database cannot answer, the engine
   returns `status=refused` with the model's explanation.
4. **Validation and execution**: the SQL goes through the shared
   `validate_sql` and runs read-only with `CHATBOT_MAX_ROWS` and
   `CHATBOT_SQL_TIMEOUT_SECONDS`.
5. **Repair**: a validation or execution error is sent back with the failed SQL
   for up to `CHATBOT_SQL_CORRECTION_ATTEMPTS` more plans.
6. **Chart**: when the question asks for a chart, the plan's chart hint and the
   executed rows become an ECharts payload through the shared visualization
   contract.
7. **Answer**: a second call writes the Portuguese answer from the executed
   result and the plan's assumptions. If that call fails, the technical result
   summary is returned instead.

Reasoning effort (`CHATBOT_LLM_REASONING_EFFORT`) is sent for `gpt-5`, `gpt-6`,
`o1`, `o3` and `o4` models. The SUS engine requires the OpenAI provider and
`OPENAI_API_KEY`.

## Legacy Engine Workflow

1. **Receive question**
   - The user sends a question through the React frontend, REST API, or CLI.
   - API requests arrive at `POST /api/chat`.

2. **Classify intent**
   - `intent.classify_question` decides whether the request is answerable,
     needs clarification, or should be refused.

3. **Retrieve database context**
   - `schema_context.retrieve_context` selects relevant tables, columns,
     relationships, caveats, and schema notes.
   - The default mode is local deterministic retrieval with enrichment.
   - LlamaIndex remains available as an optional schema retrieval path through
     configuration.

4. **Enrich context**
   - `context_retrieval.enrich_retrieved_context` adds metric rules,
     few-shot examples, related audit context, and value hints.
   - Catalog tools can resolve disease/CID terms, procedure names, and textual
     dimension values before SQL generation.

5. **Plan visualization when requested**
   - If the user asks for a chart, the chart planner creates a structured
     `ChartPlan` describing the required result shape.

6. **Generate SQL plan**
   - The SQL planning agent returns a typed `SqlPlan`.
   - The plan includes SQL, metric basis, date basis, geography basis, caveats,
     join assumptions, catalog decisions, and other debug metadata.

7. **Validate SQL**
   - `sql_validator.validate_sql` blocks mutating SQL and validates table usage,
     column usage, join policies, and common semantic mistakes.
   - Only validated `SELECT` or `WITH` queries are eligible for execution.

8. **Repair when needed**
   - If validation or execution fails, the SQL refiner agent can produce a
     corrected `SqlPlan`.
   - Corrected SQL goes through the same validation path before execution.

9. **Execute read-only query**
   - `duckdb_executor.execute_validated_sql` runs the SQL against DuckDB with
     row limits and timing metadata.

10. **Render chart payload when applicable**
    - The visualization layer validates the executed result shape and converts
      it into a chart contract plus ECharts options.

11. **Synthesize final answer**
    - The answer agent receives only the executed result and approved context.
    - The user-facing answer is concise and friendly.
    - Technical details remain available in `developer_context` when debug mode
      is enabled.

12. **Persist trace and audit data**
    - Chat traces and audit entries are written under `evaluation/chatbot/` for
      debugging and regression analysis.

## Pydantic AI Components

The legacy engine's LLM calls are implemented as Pydantic AI agents in
`src/health_system_chatbot/agents.py`.

| Agent | Output | Purpose |
|---|---|---|
| `health_system_sql_plan_agent` | `SqlPlan` | Generates the structured SQL plan |
| `health_system_sql_refiner_agent` | `SqlPlan` | Repairs SQL rejected by validation or execution |
| `health_system_chart_plan_agent` | `ChartPlan` | Plans the data shape needed for charts |
| `health_system_answer_agent` | `NaturalAnswer` | Produces the final Portuguese answer |

Typed dependency objects live in `src/health_system_chatbot/agent_deps.py`:

- `ChatDeps`
- `RefinerDeps`
- `ChartDeps`
- `AnswerDeps`

Catalog tools are registered on the SQL planning agent when
`CHATBOT_CATALOG_TOOLS_ENABLED=true`:

- `search_cid_catalog_tool`
- `search_procedure_catalog_tool`
- `search_dimension_values_tool`

## Technology Stack

Version constraints are defined in `pyproject.toml` and `frontend/package.json`.

| Layer | Technology | Role |
|---|---|---|
| Backend language | Python `>=3.12` | Agent runtime, API, evaluation |
| LLM client (SUS engine) | OpenAI Python SDK | Structured SQL plan (strict JSON schema), repair and answer calls |
| Agent framework (legacy engine) | Pydantic AI | Structured LLM agents and tool calling |
| Model provider | OpenAI (both engines); Anthropic or Ollama (legacy engine only) | Selected with `CHATBOT_LLM_PROVIDER`; default model `gpt-6-luna` |
| Optional retrieval | LlamaIndex | Optional vector schema retrieval |
| API | FastAPI + Uvicorn | REST service and frontend serving |
| Data contracts | Pydantic | API models, SQL plans, chart specs |
| SQL validation | sqlglot + project validators | Read-only SQL and semantic guardrails |
| Database | DuckDB | Local analytical database runtime |
| Frontend | React + Vite | Web chat application |
| Charts | Apache ECharts | Browser chart rendering |
| Tests | pytest + Vitest | Backend and frontend quality checks |

## Project Structure

```text
health-system-chatbot/
|-- docs/
|   |-- assets/                  # architecture diagram
|   |-- domain_catalogs/         # curated CID and procedure concepts (legacy catalog tools)
|   |-- domain_synonyms/         # clinical synonyms for catalog lookup
|   |-- generated/               # schema artifacts regenerated from the DuckDB file
|   |-- semantic_rules.json      # semantic rules with provenance (legacy engine)
|   |-- query_examples_bank.jsonl
|   `-- *_plan.md, agent_comparison_report.md   # dated design docs and reports
|-- evaluation/
|   |-- benchmark_ab/            # curated SIHRD9 benchmark: engines A/P vs agent-text-to-sql-sus
|   |-- chatbot/                 # regression runners, ablation, model and project comparisons
|   `-- ground_truth/            # historical datasets (sihrd5 schema)
|-- frontend/                    # React/Vite UI (pnpm)
|-- scripts/                     # smoke tests, artifact refresh, ground-truth tooling
|-- src/
|   `-- health_system_chatbot/
|       |-- api.py               # FastAPI app
|       |-- cli.py               # command-line interface
|       |-- chat.py              # engine dispatcher used by API and CLI
|       |-- sus/                 # SUS engine: engine, prompts, dictionary, value linker
|       |-- workflow.py          # legacy engine orchestration
|       |-- agents.py, agent_deps.py, sql_generator.py, self_correction.py
|       |-- sql_validator.py     # shared read-only and semantic SQL checks
|       |-- duckdb_executor.py   # shared read-only execution
|       |-- catalogs/, tools/    # legacy catalog retrieval and Pydantic AI tools
|       `-- visualization/       # chart intent, planning and ECharts contract
|-- tests/
|-- pyproject.toml
|-- requirements-chatbot.txt
`-- README.md
```

## Quick Start

### Prerequisites

- Python 3.12 or higher.
- Node.js 20.19 or higher.
- pnpm 9 or higher.
- An API key for the chosen LLM provider: OpenAI (`OPENAI_API_KEY`) or
  Anthropic (`ANTHROPIC_API_KEY`); no key needed for a local Ollama server.
- Local DuckDB file `sihrd9.duckdb`. By default the app looks for
  `../databases/sihrd9.duckdb` (a `databases/` folder next to this repository);
  set `CHATBOT_DB_PATH` to use another location.

The database file is intentionally not versioned. Keep it outside Git or in the
repository root as an ignored local file.

### 1. Install Backend Dependencies

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

If you prefer the pinned requirements file:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-chatbot.txt
pip install -e .
```

### 2. Configure Environment

Create a `.env` file in the repository root. With the OpenAI provider the
default SUS engine runs; Anthropic and Ollama run the legacy engine.
`CHATBOT_LLM_PROVIDER` selects the model provider used by the legacy
`pydantic_ai` agents (SQL planning, repair, chart planning, answer synthesis).
The legacy `CHATBOT_AGENT_FRAMEWORK=llamaindex`
fallback path, and the optional `CHATBOT_SCHEMA_RETRIEVAL_MODE=
llamaindex_vector` schema retrieval mode, always use OpenAI regardless of
`CHATBOT_LLM_PROVIDER` — set `OPENAI_API_KEY` if you use either of those,
even when your chosen LLM provider is Anthropic or Ollama.

**OpenAI (default):**

```env
OPENAI_API_KEY=sk-your_openai_key_here
CHATBOT_DB_PATH=/absolute/path/to/sihrd9.duckdb

# Optional
CHATBOT_LLM_PROVIDER=openai
CHATBOT_LLM_MODEL=gpt-6-luna
# none|minimal|low|medium|high|xhigh|max; empty keeps the provider default
CHATBOT_LLM_REASONING_EFFORT=low
CHATBOT_EMBED_MODEL=text-embedding-3-small
CHATBOT_AGENT_FRAMEWORK=pydantic_ai
CHATBOT_SCHEMA_RETRIEVAL_MODE=auto
CHATBOT_MAX_ROWS=200
CHATBOT_QUERY_TIMEOUT_SECONDS=60
# Cancels runaway DuckDB queries
CHATBOT_SQL_TIMEOUT_SECONDS=30
CHATBOT_SQL_CORRECTION_ATTEMPTS=2
CHATBOT_CATALOG_TOOLS_ENABLED=true
CHATBOT_ENABLE_MULTI_CANDIDATE=false
```

**Anthropic:**

```env
CHATBOT_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your_anthropic_key_here
CHATBOT_LLM_MODEL=claude-sonnet-4-5
CHATBOT_DB_PATH=/absolute/path/to/sihrd9.duckdb
```

**Ollama (local, no API key required):**

```env
CHATBOT_LLM_PROVIDER=ollama
CHATBOT_LLM_MODEL=llama3.1
CHATBOT_OLLAMA_BASE_URL=http://localhost:11434/v1
CHATBOT_DB_PATH=/absolute/path/to/sihrd9.duckdb
```

Structured output and tool-calling support vary by local model, so validate a
given Ollama model against your query workload before relying on it.

Supported values:

| Variable | Default | Notes |
|---|---|---|
| `CHATBOT_LLM_PROVIDER` | `openai` | `openai`, `anthropic`, or `ollama` (`pydantic_ai` path only) |
| `ANTHROPIC_API_KEY` | none | Required when `CHATBOT_LLM_PROVIDER=anthropic` |
| `CHATBOT_OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama's OpenAI-compatible endpoint; falls back to `OLLAMA_BASE_URL` |
| `CHATBOT_OLLAMA_API_KEY` | none | Optional, for remote/secured Ollama-compatible endpoints; falls back to `OLLAMA_API_KEY` |
| `CHATBOT_CHAT_ENGINE` | `auto` | `auto`, `sus`, or `legacy` for the API and chat CLI |
| `CHATBOT_AGENT_FRAMEWORK` | `pydantic_ai` | `pydantic_ai` or `llamaindex` (`llamaindex` is OpenAI-only) |
| `CHATBOT_SCHEMA_RETRIEVAL_MODE` | `auto` | `auto`, `keyword`, or `llamaindex_vector` (`llamaindex_vector` is OpenAI-only) |
| `CHATBOT_CATALOG_RETRIEVAL_MODE` | `lexical` | Local catalog retrieval mode |
| `CHATBOT_CATALOG_TOOLS_ENABLED` | `true` | Enables CID/procedure/dimension lookup tools |

### 3. Start the API

```bash
PYTHONPATH=src .venv/bin/python -m uvicorn health_system_chatbot.api:app \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

Open:

- API root and frontend: `http://127.0.0.1:8000`
- Swagger docs: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

### 4. Install and Build the Frontend

```bash
cd frontend
pnpm install
pnpm build
```

When `frontend/dist/index.html` exists, FastAPI serves the React build at
`GET /`. Without that build, FastAPI falls back to the legacy static HTML in
`src/health_system_chatbot/static/index.html`.

For frontend development with Vite:

```bash
cd frontend
pnpm dev
```

The Vite dev server runs at `http://127.0.0.1:5173` and proxies `/api` requests
to `http://127.0.0.1:8000`.

## Usage

### CLI

Show safe runtime configuration:

```bash
.venv/bin/python -m health_system_chatbot.cli config
```

Ask a single question:

```bash
.venv/bin/python -m health_system_chatbot.cli ask \
  "Quantas internacoes existem?" \
  --show-sql
```

Ask many questions from a file:

```bash
.venv/bin/python -m health_system_chatbot.cli ask-file perguntas.txt --show-sql
```

Inspect retrieved context:

```bash
.venv/bin/python -m health_system_chatbot.cli context \
  "Mortes por cancer em mulheres acima de 50 anos em Porto Alegre"
```

Validate and execute read-only SQL:

```bash
.venv/bin/python -m health_system_chatbot.cli run-sql \
  "SELECT COUNT(*) AS total FROM internacao"
```

All subcommands:

| Command | Engine | Purpose |
|---|---|---|
| `config` | — | Show the safe runtime configuration (no secrets) |
| `ask`, `ask-file` | dispatcher (SUS by default) | Answer one question, or every line of a text file |
| `audit-log` | — | Inspect the append-only chat audit log |
| `context` | legacy | Show the schema context retrieved for a question |
| `draft-sql` | legacy | Draft a structured SQL plan without executing it |
| `validate-sql` | shared | Validate a SQL string without executing it |
| `run-sql` | shared | Validate and execute SQL read-only |
| `eval` | legacy | Evaluate against a ground-truth dataset |
| `index` | legacy | Manage the optional LlamaIndex schema index |

### Example Questions

```text
Quantas internacoes existem?
Quantos partos aconteceram?
Quantas mulheres acima de 50 anos morreram por cancer em Porto Alegre?
Qual a distribuicao de internacoes por sexo?
Gere um grafico de barras com a distribuicao de internacoes por sexo.
Mostre a evolucao anual de mortes por cancer.
Quais municipios do RS tiveram mais internacoes?
```

## API

The REST API is implemented in `src/health_system_chatbot/api.py`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Serves the React build or static fallback |
| `GET` | `/health` | Basic API health check |
| `GET` | `/api/health` | Frontend health endpoint |
| `GET` | `/api/agent-health` | Agent configuration and status |
| `POST` | `/api/chat` | Main chat endpoint |
| `GET` | `/api/schema` | Schema context for all tables or one table |
| `GET` | `/api/models` | Current model/provider configuration |
| `GET` | `/api/database/overview` | Known table inventory |
| `GET` | `/api/database/table/{schema}/{table}` | Columns and sample rows |
| `POST` | `/api/database/query` | Validated read-only SQL explorer query |

Example chat request:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Quantas internacoes existem?",
    "show_sql": true,
    "show_debug": true,
    "allow_llm": true
  }'
```

Example response fields:

| Field | Meaning |
|---|---|
| `answer_pt` | User-facing answer in Portuguese |
| `sql` | Generated and validated SQL, included for debug/API use |
| `result_summary` | Compact technical summary |
| `caveats` | Relevant caveats for interpretation |
| `evidence` | Execution metadata such as row count and elapsed time |
| `developer_context` | Debug metadata for developers |
| `chart` | Optional chart contract and ECharts options |
| `status` | `answered`, `clarified`, `refused`, or `failed` |

## Frontend

The frontend is a React/Vite application under `frontend/`.

User-facing title:

```text
Datasus Health System Chatbot
DaVint Lab · SIH/SUS
```

Frontend responsibilities:

- Chat composer and message history.
- Debug mode toggle.
- Optional SQL display.
- Developer debug panel.
- Schema explorer.
- Health/status display.
- Chart rendering from `chart.echarts` using Apache ECharts.

Important files:

| File | Purpose |
|---|---|
| `frontend/src/hooks/use-chat.js` | Sends questions to `POST /api/chat` |
| `frontend/src/lib/chat-utils.js` | Normalizes backend `ChatbotAnswer` payloads |
| `frontend/src/components/results/ChartPanel.jsx` | Renders ECharts charts |
| `frontend/src/components/results/DebugPanel.jsx` | Renders debug metadata |
| `frontend/src/components/schema/SchemaExplorer.jsx` | Shows schema context |
| `frontend/src/components/layout/AppHeader.jsx` | Main app header and controls |

## Evaluation

The repository includes evaluation and regression tooling for Text-to-SQL
quality, chart generation, and runtime behavior.

Useful commands:

```bash
.venv/bin/pytest -q
```

```bash
cd frontend
pnpm test
```

```bash
.venv/bin/python scripts/chat_smoke.py
```

```bash
.venv/bin/python evaluation/chatbot/evaluate_extraction_accuracy.py \
  --limit 10 \
  --run-id local_smoke
```

```bash
.venv/bin/python scripts/evaluate_chart_generation.py \
  --run-id chart_smoke
```

Run a Text-to-SQL ablation or direct OpenAI baseline evaluation:

```bash
.venv/bin/python evaluation/chatbot/run_ablation.py \
  --suite smoke_10 \
  --run-id ablation_smoke_10 \
  --overwrite
```

Example focused run without OpenAI baselines:

```bash
.venv/bin/python evaluation/chatbot/run_ablation.py \
  --dataset evaluation/ground_truth/stage1_questions_v2.jsonl \
  --variants full_agent,no_catalog_tools,no_self_correction \
  --limit 10 \
  --run-id agent_ablation_10
```

Evaluation artifacts are written under `evaluation/chatbot/results/`. Chat
traces and audit logs are stored under `evaluation/chatbot/` for inspection and
debugging. The runners above exercise the legacy engine; most of the datasets
under `evaluation/ground_truth/` were written for the older sihrd5 schema
(`internacoes`) and are kept as history.

### SIHRD9 benchmark (engines and projects)

[`evaluation/benchmark_ab/`](evaluation/benchmark_ab/README.md) compares, on the
same questions, database, model (`gpt-6-luna`) and reasoning effort:

- **A**: this project's legacy engine;
- **P**: this project's product path (SUS engine);
- **B**: the sibling project `agent-text-to-sql-sus`.

Its ground truth has 281 questions migrated to SIHRD9 and curated again (every
gold executed on the database, each decision recorded with its reason in
`curation.yaml`). It reports execution accuracy of the final SQL and, separately,
whether the written answer is correct, as judged by a blind LLM judge. The
README in that folder explains the method and how to reproduce a run.

[`evaluation/chatbot/project_comparison/`](evaluation/chatbot/project_comparison/README.md)
holds an earlier, smaller comparison (12 and then 32 questions) with its own
runner and results.

## Observability

The runtime keeps technical metadata separate from the final answer shown to
the user.

Important observability outputs:

- `evaluation/chatbot/audit/chat_audit.jsonl`: append-only chat audit log.
- `evaluation/chatbot/traces/`: per-question runtime traces.
- `evaluation/chatbot/results/`: evaluation outputs.
- `developer_context` in API responses: retrieved tables, catalog decisions,
  metric basis, chart planning, value hints, warnings, and related context.

The frontend only shows developer details when debug mode is enabled.

## Database Notes

The primary database is `sihrd9.duckdb` (about 30 GB, admissions from 2008-01-01
to 2025-12-31). It must not be committed to Git.

Schema facts both engines rely on. The full measured list lives in the SUS
dictionary [`sus/sihrd9.yaml`](src/health_system_chatbot/sus/sihrd9.yaml), and
the legacy engine's join policy in `docs/generated/join_policy.csv`.

- The fact table is `internacao`, one row per AIH. `N_AIH` is unique.
- Procedures live only in `internacao_procedimento`. Long-stay AIHs repeat rows,
  so count admissions with `COUNT(DISTINCT N_AIH)` or `EXISTS`.
- There are two geographies. `internacao.MUNIC_RES` is the patient's residence.
  `internacao.CNES -> hospital.CNES -> hospital.MUNIC_MOV` is the place of care,
  covering 100% of admissions. They differ for about 32% of admissions.
- `municipios` has the Federal District only as 530010 (Brasília). The
  administrative-region codes 5300xx used by the fact table (1.26 million
  admissions) and by 23 hospitals must be mapped to Brasília/DF.
- `internacao.ESPEC` uses the AIH bed-specialty coding (2 = obstetric,
  7 = pediatric). The `especialidade` table uses another coding, so joining
  them mislabels every specialty.
- `RACA_COR = 99` ("sem informação", 22.9% of admissions) is not in the
  `raca_cor` dimension, so use a `LEFT JOIN`.
- `SEXO` only has 1 (male) and 3 (female). COVID-19 is coded `B342`; `U07`
  never occurs.
- `DIAG_SECUN`, `CID_MORTE` and `CID_NOTIF` use `''` as empty until 2014 and
  `'0000'` from 2015 on. Secondary diagnoses move to `DIAGSEC1..9` from 2015,
  and `CID_MORTE` has real values only for 2008-2014.
- `cid_manuais` and `procedimentos_manuais` complement `cid` and `procedimentos`
  with codes missing from the main catalogs.
- `tempo` covers only 2008-2024. `socioeconomico` has no 2010, 2022, 2023 or
  2025. Discharges in November and December 2025 are incomplete.

When the database file is replaced, regenerate the schema artifacts the runtime
loads:

```bash
python scripts/refresh_db_artifacts.py
```

Ignored local database files:

- `*.duckdb`
- `*.duckdb.wal`
- `*.duckdb.tmp`

The SQL executor opens the database in read-only mode and only executes SQL that
passes validation.
