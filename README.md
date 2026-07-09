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

The project is designed as an AI engineering system rather than a prompt-only
demo. The runtime separates schema/context grounding, catalog lookup, SQL
planning, deterministic validation, execution feedback, chart planning, and
final answer synthesis.

## Contents

- [What This Project Is](#what-this-project-is)
- [Architecture](#architecture)
- [Agent Workflow](#agent-workflow)
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
- SQL generation with structured Pydantic AI outputs.
- Local catalog tools for CID, procedure, and dimension-value grounding.
- Deterministic SQL guardrails before execution.
- Execution feedback and self-correction for repairable SQL failures.
- Optional multi-candidate SQL generation and deterministic ranking.
- Natural-language answer synthesis separated from technical debug metadata.
- Optional chart generation with Apache ECharts-compatible payloads.
- CLI, FastAPI REST API, and React/Vite web frontend.
- Regression and evaluation runners against curated question sets.

## Architecture

![Health System Chatbot architecture](docs/assets/chatbot-architecture.svg)

The application has one central runtime path used by both the CLI and the REST
API. The web frontend talks to the FastAPI backend, and the backend calls the
same `workflow.run_chat` pipeline used by the command-line interface.

Main layers:

| Layer | Responsibility |
|---|---|
| React/Vite frontend | Chat UI, debug mode, schema explorer, SQL display, chart rendering |
| FastAPI API | HTTP adapter for chat, schema, health, model info, and database explorer endpoints |
| Workflow runtime | Orchestrates classification, context, SQL planning, validation, execution, charting, and answer synthesis |
| Pydantic AI agents | Structured LLM calls for SQL planning, SQL repair, chart planning, and natural answer generation |
| Catalog tools | Local lookup for CID concepts, procedures, and dimension values |
| Validation layer | Read-only SQL checks, table/column checks, join policies, and safety constraints |
| DuckDB executor | Executes validated SQL against the local `sihrd5.duckdb` database in read-only mode |
| Evaluation layer | Runs curated datasets, stores traces, summaries, and error analysis artifacts |

## Agent Workflow

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

The core LLM calls are implemented as Pydantic AI agents in
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
| Agent framework | Pydantic AI | Structured LLM agents and tool calling |
| Model provider | OpenAI | SQL planning, repair, chart planning, answer synthesis |
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
|   |-- database_overview.md
|   |-- schema_catalog.md
|   |-- business_dictionary.md
|   |-- relationship_map.md
|   |-- data_quality_report.md
|   |-- query_design_methodology.md
|   |-- assets/
|   `-- generated/
|-- evaluation/
|   |-- chatbot/
|   `-- ground_truth/
|-- frontend/
|   |-- src/
|   |-- package.json
|   |-- pnpm-lock.yaml
|   `-- vite.config.mjs
|-- scripts/
|   |-- chat_smoke.py
|   |-- evaluate_chatbot.py
|   |-- evaluate_chart_generation.py
|   |-- sihrd5_stage1.py
|   `-- verify_stage1.py
|-- src/
|   `-- health_system_chatbot/
|       |-- agents.py
|       |-- agent_deps.py
|       |-- api.py
|       |-- workflow.py
|       |-- sql_generator.py
|       |-- sql_validator.py
|       |-- duckdb_executor.py
|       |-- catalogs/
|       |-- tools/
|       `-- visualization/
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
- OpenAI API key.
- Local DuckDB file, typically `sihrd5.duckdb`.

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

Create a `.env` file in the repository root:

```env
OPENAI_API_KEY=sk-your_openai_key_here
CHATBOT_DB_PATH=/absolute/path/to/sihrd5.duckdb

# Optional
CHATBOT_LLM_MODEL=gpt-4.1-mini
CHATBOT_EMBED_MODEL=text-embedding-3-small
CHATBOT_AGENT_FRAMEWORK=pydantic_ai
CHATBOT_SCHEMA_RETRIEVAL_MODE=auto
CHATBOT_MAX_ROWS=200
CHATBOT_QUERY_TIMEOUT_SECONDS=60
CHATBOT_SQL_CORRECTION_ATTEMPTS=2
CHATBOT_CATALOG_TOOLS_ENABLED=true
CHATBOT_ENABLE_MULTI_CANDIDATE=false
```

Supported values:

| Variable | Default | Notes |
|---|---|---|
| `CHATBOT_AGENT_FRAMEWORK` | `pydantic_ai` | `pydantic_ai` or `llamaindex` |
| `CHATBOT_SCHEMA_RETRIEVAL_MODE` | `auto` | `auto`, `keyword`, or `llamaindex_vector` |
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
  "SELECT COUNT(*) AS total FROM internacoes"
```

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
DaVint Lab - Pydantic AI
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
debugging.

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

The primary database is `sihrd5.duckdb`. It can be large and must not be
committed to Git.

Ignored local database files:

- `*.duckdb`
- `*.duckdb.wal`
- `*.duckdb.tmp`

The SQL executor opens the database in read-only mode and only executes SQL that
passes validation.
