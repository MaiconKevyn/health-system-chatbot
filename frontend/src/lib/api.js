import { API_BASE_URL } from "./constants";

function buildHeaders(hasBody) {
  const headers = {
    Accept: "application/json",
    "X-Requested-With": "XMLHttpRequest"
  };

  if (hasBody) {
    headers["Content-Type"] = "application/json";
  }

  return headers;
}

async function requestJson(path, options = {}) {
  const { method = "GET", body, fetcher = fetch } = options;
  const hasBody = body !== undefined;
  const response = await fetcher(`${API_BASE_URL}${path}`, {
    method,
    headers: buildHeaders(hasBody),
    credentials: "include",
    mode: "cors",
    cache: "no-cache",
    ...(hasBody ? { body: JSON.stringify(body) } : {})
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  return response.json();
}

export function sendQuery({ question, sessionId, debug } = {}) {
  return requestJson("/chat", {
    method: "POST",
    body: {
      question,
      session_id: sessionId,
      show_sql: Boolean(debug),
      show_debug: Boolean(debug),
      allow_llm: true
    }
  });
}

export function getWebHealth() {
  return requestJson("/health");
}

export function getAgentHealth() {
  return requestJson("/agent-health");
}

export function getSchema(tableName = "") {
  const query = tableName ? `?table=${encodeURIComponent(tableName)}` : "";
  return requestJson(`/schema${query}`);
}

export function getDatabaseOverview() {
  return requestJson("/database/overview");
}

export function getDatabaseTable(schemaName, tableName, limit = 25) {
  const query = `?limit=${encodeURIComponent(limit)}`;
  return requestJson(
    `/database/table/${encodeURIComponent(schemaName)}/${encodeURIComponent(tableName)}${query}`
  );
}

export function runDatabaseQuery({ sql, limit = 100 } = {}) {
  return requestJson("/database/query", {
    method: "POST",
    body: { sql, limit }
  });
}
