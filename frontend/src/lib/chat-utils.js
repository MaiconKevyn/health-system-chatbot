import { MAX_HISTORY_MESSAGES } from "./constants";

function getDefaultEnvironment() {
  if (typeof window !== "undefined") return window;
  return globalThis;
}

function getNow(environment) {
  return typeof environment?.now === "function" ? environment.now() : Date.now();
}

function getRandom(environment) {
  return typeof environment?.random === "function" ? environment.random() : Math.random();
}

export function createSessionId(environment = getDefaultEnvironment()) {
  if (typeof environment?.crypto?.randomUUID === "function") {
    return environment.crypto.randomUUID();
  }

  const now = getNow(environment);
  const random = getRandom(environment);
  return `web-${now}-${random.toString(16).slice(2)}`;
}

export function createMessageId(environment = getDefaultEnvironment()) {
  const now = getNow(environment);
  const random = getRandom(environment);
  return `msg-${now}-${random.toString(16).slice(2)}`;
}

export function createMessage(content, options = {}) {
  const normalizedOptions = typeof options === "string" ? { type: options } : options ?? {};
  const {
    type = "assistant",
    metadata = null,
    now = new Date(),
    idFactory = createMessageId
  } = normalizedOptions;
  const timestamp = now instanceof Date ? now.toISOString() : new Date(now).toISOString();

  return {
    id: idFactory(),
    content,
    type,
    timestamp,
    metadata
  };
}

export function trimPersistedHistory(messages) {
  if (!Array.isArray(messages)) return [];

  return messages
    .filter((message) => message?.type !== "error")
    .slice(-MAX_HISTORY_MESSAGES);
}

function buildQueryMetadata(data, debugEnabled) {
  const pydanticDebug = debugEnabled ? buildPydanticDebug(data) : null;
  const metadata = {
    sql: data?.sql || data?.sql_query || null,
    chart: data?.chart || null
  };

  if (Number.isFinite(data?.execution_time)) {
    metadata.executionTime = data.execution_time;
  }
  if (Number.isFinite(data?.evidence?.elapsed_seconds)) {
    metadata.executionTime = data.evidence.elapsed_seconds;
  }

  if (debugEnabled) {
    metadata.debug = data?.debug || pydanticDebug;
    metadata.agentMetadata = data?.metadata || data?.developer_context || {};
  }

  return metadata;
}

function pydanticStatusIsSuccessful(status) {
  return ["answered", "clarified", "refused"].includes(status);
}

function buildDebugStep(node, title, data = {}) {
  return {
    index: undefined,
    node,
    title,
    data
  };
}

export function buildPydanticDebug(data) {
  if (!data || typeof data !== "object") return null;

  const developerContext =
    data.developer_context && typeof data.developer_context === "object"
      ? data.developer_context
      : {};
  const steps = [];

  if (data.sql) {
    steps.push(
      buildDebugStep("sql", "SQL", {
        generated_sql: data.sql,
        validated_sql: data.sql
      })
    );
  }

  if (data.result_summary || data.answer_pt) {
    steps.push(
      buildDebugStep("answer", "Resposta", {
        final_response: data.answer_pt,
        result_summary: data.result_summary,
        caveats: data.caveats || []
      })
    );
  }

  if (Object.keys(developerContext).length > 0) {
    steps.push(buildDebugStep("developer_context", "Contexto tecnico", developerContext));
  }

  if (data.chart) {
    steps.push(
      buildDebugStep("chart", "Grafico", {
        chart: data.chart,
        chart_plan: developerContext.chart_plan,
        chart_spec: developerContext.chart_spec,
        chart_warnings: developerContext.chart_warnings
      })
    );
  }

  if (data.evidence && typeof data.evidence === "object") {
    steps.push(buildDebugStep("evidence", "Evidencia", data.evidence));
  }

  return steps.length ? { steps } : null;
}

export function normalizeQueryResponse(data, debugEnabled = false) {
  const success = data?.success === true || pydanticStatusIsSuccessful(data?.status);
  const failed = data?.success === false || data?.status === "failed";

  return {
    type: success && !failed ? "assistant" : "error",
    content: success && !failed
      ? data?.answer_pt ||
        data?.response ||
        data?.conversational_response ||
        data?.answer ||
        "Consulta processada com sucesso."
      : data?.error_message ||
        data?.answer_pt ||
        data?.answer ||
        data?.response ||
        "Nao foi possivel processar a consulta.",
    metadata: buildQueryMetadata(data, debugEnabled)
  };
}

export function buildUserFacingError(error) {
  const message = error?.message || String(error);

  if (message.includes("Failed to fetch") || message.includes("NetworkError")) {
    return "Nao foi possivel conectar a API do Health System Chatbot. Confirme se o servico esta rodando e tente novamente.";
  }
  if (message.includes("HTTP 429")) {
    return "Muitas consultas em pouco tempo. Aguarde alguns segundos antes de tentar novamente.";
  }
  if (message.includes("HTTP 5")) {
    return "O agente retornou erro interno. Tente novamente em alguns instantes ou refine o recorte da consulta.";
  }
  return `Erro de conexao: ${message}`;
}
